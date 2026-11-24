"""Storing ticket attachments uploaded through the API.

Browsers used to upload straight to the ticket-attachments bucket with the
public anon key, which meant the bucket had to accept writes from anyone.
Uploads now come through the API: the caller is authenticated and authorised
for the ticket, the file type is read from the file's own bytes (never its
name or the browser's Content-Type), the size is capped, and the object name
is generated here. Storage is written with the server's service-role client.
"""
from __future__ import annotations

import logging
import unicodedata
import uuid
from typing import Any, Optional

from app.services.image_upload_service import (
    CONTENT_TYPES,
    StorageFailed,
    StorageUnavailable,
    validate_image,
)

log = logging.getLogger(__name__)

ATTACHMENT_BUCKET = "ticket-attachments"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_FILENAME_CHARS = 255


def clean_filename(name: Optional[str]) -> Optional[str]:
    """The display name only: no directories, control characters or overlong names."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return printable[:MAX_FILENAME_CHARS] or None


def store_ticket_attachment(
    db: Any, *, ticket: Any, uploaded_by: Any, content: bytes, original_filename: Optional[str]
) -> Any:
    """Validate, upload and record one attachment; return the TicketAttachment row.

    Raises ImageTooLarge / UnsupportedImage for a bad file, StorageUnavailable
    when storage is not configured and StorageFailed when it rejects the upload.
    If the database write fails, the uploaded object is removed again so no
    orphan is left behind.
    """
    from app.core.storage import supabase_storage
    from app.models import TicketAttachment

    ext = validate_image(content, MAX_ATTACHMENT_BYTES)
    client = supabase_storage.client
    if client is None:
        raise StorageUnavailable("Attachment storage is not configured.")

    object_path = f"{ticket.id}/{uuid.uuid4().hex}.{ext}"
    bucket = client.storage.from_(ATTACHMENT_BUCKET)
    try:
        bucket.upload(path=object_path, file=content, file_options={"content-type": CONTENT_TYPES[ext]})
        public_url = str(bucket.get_public_url(object_path)).rstrip("?")
    except Exception as exc:
        log.warning("Attachment upload failed for ticket %s: %s", ticket.id, exc)
        raise StorageFailed("The attachment could not be stored. Please try again.") from exc

    row = TicketAttachment(
        ticket_id=ticket.id,
        file_path=public_url,
        mime_type=CONTENT_TYPES[ext],
        original_filename=clean_filename(original_filename),
        uploaded_by=uploaded_by,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _remove_quietly(bucket, object_path)
        raise
    db.refresh(row)
    return row


def _remove_quietly(bucket: Any, object_path: str) -> None:
    try:
        bucket.remove([object_path])
    except Exception as exc:  # the original error matters more; log this one
        log.error("Could not remove orphaned attachment %s: %s", object_path, exc)
