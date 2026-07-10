from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user
from app.models import Profile, Ticket, TicketComment
from app.schemas.misc import TicketCommentCreate, TicketCommentOut

router = APIRouter(
    prefix="/ticket-comments",
    tags=["Ticket Comments"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=TicketCommentOut)
def create_ticket_comment(payload: TicketCommentCreate, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    user = db.query(Profile).filter(Profile.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    obj = TicketComment(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketCommentOut])
def list_ticket_comments(
    ticket_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(TicketComment)
    if ticket_id:
        q = q.filter(TicketComment.ticket_id == ticket_id)
    return q.order_by(TicketComment.created_at.asc()).offset(offset).limit(limit).all()


@router.delete("/{comment_id}")
def delete_ticket_comment(comment_id: str, db: Session = Depends(get_db)):
    obj = db.query(TicketComment).filter(TicketComment.id == comment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Comment not found")
    db.delete(obj)
    db.commit()
    return {"message": "Comment deleted"}
