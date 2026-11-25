"""Ticket attachments for the staff ticket views.

Files are uploaded through POST /ticket-attachments/upload, never straight to
storage from the browser (see app/services/attachment_service.py).
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.errors import upload_error
from app.deps import get_db, get_current_user, is_admin_role, assert_in_active_warehouse, scoped_warehouse_id
from app.models import Ticket, TicketAttachment, Profile
from app.schemas.misc import TicketAttachmentOut
from app.services import attachment_service, image_upload_service
from app.services.ticket_access import can_view_ticket

router = APIRouter(prefix="/ticket-attachments", tags=["Ticket Attachments"])


@router.post("/upload", response_model=TicketAttachmentOut, status_code=201)
def upload_ticket_attachment(
    ticket_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Attach an image (JPG, PNG, WebP or GIF, up to 10 MB) to a ticket the
    caller can see. 404 for a ticket outside the caller's scope, so its
    existence is not revealed."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or not can_view_ticket(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Read one byte past the limit so an oversized file is rejected without
    # holding more of it in memory.
    content = file.file.read(attachment_service.MAX_ATTACHMENT_BYTES + 1)
    try:
        return attachment_service.store_ticket_attachment(
            db, ticket=ticket, uploaded_by=current_user.id, content=content,
            original_filename=file.filename,
        )
    except (image_upload_service.ImageTooLarge, image_upload_service.UnsupportedImage,
            image_upload_service.StorageUnavailable, image_upload_service.StorageFailed) as exc:
        raise upload_error(exc) from exc


@router.get("/", response_model=list[TicketAttachmentOut])
def list_ticket_attachments(
    ticket_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    if ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket or not can_view_ticket(ticket, current_user):
            raise HTTPException(status_code=404, detail="Ticket not found")
        q = db.query(TicketAttachment).filter(TicketAttachment.ticket_id == ticket_id)
    elif is_admin_role(current_user):
        q = db.query(TicketAttachment).join(Ticket, Ticket.id == TicketAttachment.ticket_id).filter(
            Ticket.warehouse_id == scoped_warehouse_id(current_user)
        )
    else:
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        q = db.query(TicketAttachment).join(Ticket, Ticket.id == TicketAttachment.ticket_id)
        if user_wh_id is not None:
            q = q.filter(
                (Ticket.warehouse_id == user_wh_id) |
                (Ticket.created_by == uid) |
                (Ticket.assigned_to == uid)
            )
        else:
            q = q.filter((Ticket.created_by == uid) | (Ticket.assigned_to == uid))
    return q.order_by(TicketAttachment.created_at.desc()).all()


@router.delete("/{attachment_id}")
def delete_ticket_attachment(attachment_id: str, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    obj = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket attachment not found")
    if is_admin_role(current_user):
        parent = db.query(Ticket).filter(Ticket.id == obj.ticket_id).first()
        assert_in_active_warehouse(current_user, parent.warehouse_id if parent else None, "Ticket attachment")
    if not is_admin_role(current_user) and str(obj.uploaded_by) != str(getattr(current_user, "id", "")):
        raise HTTPException(status_code=403, detail="You can only delete your own attachments.")
    db.delete(obj)
    db.commit()
    return {"message": "Ticket attachment deleted"}