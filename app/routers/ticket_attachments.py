from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user
from app.models import TicketAttachment, Profile
from app.schemas.misc import TicketAttachmentCreate, TicketAttachmentOut

router = APIRouter(prefix="/ticket-attachments", tags=["Ticket Attachments"])


@router.post("/", response_model=TicketAttachmentOut)
def create_ticket_attachment(payload: TicketAttachmentCreate, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    obj = TicketAttachment(**payload.model_dump())
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
    q = db.query(TicketAttachment)
    if ticket_id:
        q = q.filter(TicketAttachment.ticket_id == ticket_id)
    return q.order_by(TicketAttachment.created_at.desc()).all()


@router.delete("/{attachment_id}")
def delete_ticket_attachment(attachment_id: str, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    obj = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket attachment not found")
    db.delete(obj)
    db.commit()
    return {"message": "Ticket attachment deleted"}