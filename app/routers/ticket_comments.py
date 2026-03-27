from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import TicketComment
from app.schemas.misc import TicketCommentCreate, TicketCommentOut

router = APIRouter(prefix="/ticket-comments", tags=["Ticket Comments"])


@router.post("/", response_model=TicketCommentOut)
def create_ticket_comment(payload: TicketCommentCreate, db: Session = Depends(get_db)):
    obj = TicketComment(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketCommentOut])
def list_ticket_comments(
    ticket_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(TicketComment)
    if ticket_id:
        q = q.filter(TicketComment.ticket_id == ticket_id)
    return q.order_by(TicketComment.created_at.desc()).all()