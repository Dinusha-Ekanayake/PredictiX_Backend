"""Validating and storing uploaded images (asset photos).

The image type is read from the file's own bytes, never from its name or the
browser's Content-Type, and the stored object name is generated here, so
nothing the client controls reaches storage.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

ASSET_IMAGE_BUCKET = "asset-images"
MAX_ASSET_IMAGE_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


class ImageTooLarge(Exception):
    pass


class UnsupportedImage(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class StorageFailed(Exception):
    pass


def image_extension(content: bytes) -> Optional[str]:
    """jpg, png, gif or webp from the file signature, else None."""
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image(content: bytes, max_bytes: int) -> str:
    """Return the image extension, or raise ImageTooLarge / UnsupportedImage."""
    if len(content) > max_bytes:
        raise ImageTooLarge(f"Images must be {max_bytes // (1024 * 1024)} MB or smaller.")
    ext = image_extension(content)
    if ext is None:
        raise UnsupportedImage("Upload a JPG, PNG, WebP or GIF image.")
    return ext


def add_asset_image(db: Any, asset: Any, content: bytes) -> Any:
    """Store a photo of `asset` and append its public URL to metadata.images.

    The caller has already checked the user may edit the asset.
    """
    from app.core.storage import supabase_storage

    ext = validate_image(content, MAX_ASSET_IMAGE_BYTES)
    client = supabase_storage.client
    if client is None:
        raise StorageUnavailable("Image storage is not configured.")
    object_path = f"{asset.id}/{uuid.uuid4().hex}.{ext}"
    try:
        supabase_storage._ensure_bucket_exists(ASSET_IMAGE_BUCKET)
        bucket = client.storage.from_(ASSET_IMAGE_BUCKET)
        bucket.upload(path=object_path, file=content, file_options={"content-type": CONTENT_TYPES[ext]})
        image_url = str(bucket.get_public_url(object_path)).rstrip("?")
    except Exception as exc:
        log.warning("Asset image upload failed for %s: %s", asset.id, exc)
        raise StorageFailed("The image could not be stored. Please try again.") from exc

    # A new dict, so SQLAlchemy sees the JSONB column as changed.
    meta = dict(asset.meta or {})
    meta["images"] = [*(meta.get("images") or []), image_url]
    asset.meta = meta
    db.commit()
    db.refresh(asset)
    return asset
