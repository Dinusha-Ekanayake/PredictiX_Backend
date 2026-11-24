from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user, get_current_user, assert_in_active_warehouse
from app.models import Profile, Ticket, TicketStatusHistory
from app.schemas.misc import TicketStatusHistoryCreate, TicketStatusHistoryOut
from app.services.ticket_access import can_view_ticket

router = APIRouter(
    prefix="/ticket-status-history",
    tags=["Ticket Status History"],
    dependencies=[Depends(require_user)],
)


# Status history is an audit trail. This endpoint took no caller identity, so
# any authenticated user could append arbitrary transitions to any ticket, 
# including ones they cannot even view, and attribute them to whoever they
# liked. The application writes history itself when a ticket actually changes
# (see the ticket services), so nothing in the product posts here.
@router.post("/", response_model=TicketStatusHistoryOut, dependencies=[Depends(require_admin)])
def create_ticket_status_history(
    payload: TicketStatusHistoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    assert_in_active_warehouse(current_user, ticket.warehouse_id, "Ticket")

    obj = TicketStatusHistory(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketStatusHistoryOut])
def list_ticket_status_history(
    ticket_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    # A ticket_id is required so this can be scoped. Without one, any
    # authenticated user could pull every ticket's status history fleet-wide,
    # leaking cross-warehouse ticket activity.
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id is required")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or not can_view_ticket(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket not found")

    return (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket_id)
        .order_by(TicketStatusHistory.created_at.desc())
        .all()
    )