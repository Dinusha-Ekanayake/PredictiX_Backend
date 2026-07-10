from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user
from app.models import Ticket, TicketStatusHistory
from app.schemas.misc import TicketStatusHistoryCreate, TicketStatusHistoryOut

router = APIRouter(
    prefix="/ticket-status-history",
    tags=["Ticket Status History"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=TicketStatusHistoryOut)
def create_ticket_status_history(payload: TicketStatusHistoryCreate, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    obj = TicketStatusHistory(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketStatusHistoryOut])
def list_ticket_status_history(
    ticket_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(TicketStatusHistory)
    if ticket_id:
        q = q.filter(TicketStatusHistory.ticket_id == ticket_id)
    return q.order_by(TicketStatusHistory.created_at.desc()).all()