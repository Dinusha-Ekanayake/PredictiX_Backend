from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, is_admin_role
from app.models import Ticket, TicketAttachment, Profile
from app.schemas.misc import TicketAttachmentCreate, TicketAttachmentOut

router = APIRouter(prefix="/ticket-attachments", tags=["Ticket Attachments"])


def _can_view_ticket(ticket: Ticket, current_user: Profile) -> bool:
    """Same rule as tickets.py's list scoping: admins see everything,
    a regular user only tickets they created or are assigned to."""
    if is_admin_role(current_user):
        return True
    uid = str(getattr(current_user, "id", ""))
    return str(ticket.created_by) == uid or str(ticket.assigned_to) == uid


@router.post("/", response_model=TicketAttachmentOut)
def create_ticket_attachment(payload: TicketAttachmentCreate, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _can_view_ticket(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket not found")

    # uploaded_by is always the authenticated caller — never trust a
    # client-supplied value.
    data = payload.model_dump()
    data["uploaded_by"] = current_user.id

    obj = TicketAttachment(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketAttachmentOut])
def list_ticket_attachments(
    ticket_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    if ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket or not _can_view_ticket(ticket, current_user):
            raise HTTPException(status_code=404, detail="Ticket not found")
        q = db.query(TicketAttachment).filter(TicketAttachment.ticket_id == ticket_id)
    elif is_admin_role(current_user):
        q = db.query(TicketAttachment)
    else:
        uid = str(getattr(current_user, "id", ""))
        q = (
            db.query(TicketAttachment)
            .join(Ticket, Ticket.id == TicketAttachment.ticket_id)
            .filter((Ticket.created_by == uid) | (Ticket.assigned_to == uid))
        )
    return q.order_by(TicketAttachment.created_at.desc()).all()


@router.delete("/{attachment_id}")
def delete_ticket_attachment(attachment_id: str, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    obj = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket attachment not found")
    if not is_admin_role(current_user) and str(obj.uploaded_by) != str(getattr(current_user, "id", "")):
        raise HTTPException(status_code=403, detail="You can only delete your own attachments.")
    db.delete(obj)
    db.commit()
    return {"message": "Ticket attachment deleted"}