from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user, get_current_user, is_admin_role
from app.models import Profile, Ticket, TicketStatusHistory
from app.schemas.misc import TicketStatusHistoryCreate, TicketStatusHistoryOut

router = APIRouter(
    prefix="/ticket-status-history",
    tags=["Ticket Status History"],
    dependencies=[Depends(require_user)],
)


def _can_view_ticket(ticket: Ticket, current_user: Profile) -> bool:
    """Same rule as tickets.py's get_ticket/list scoping — see there for
    the full rationale."""
    if is_admin_role(current_user):
        return True
    uid = str(getattr(current_user, "id", ""))
    user_wh_id = getattr(current_user, "warehouse_id", None)
    if user_wh_id is not None and str(ticket.warehouse_id) == str(user_wh_id):
        return True
    return str(ticket.created_by) == uid or str(ticket.assigned_to) == uid


# Status history is an audit trail. This endpoint took no caller identity, so
# any authenticated user could append arbitrary transitions to any ticket —
# including ones they cannot even view — and attribute them to whoever they
# liked. The application writes history itself when a ticket actually changes
# (see the ticket services), so nothing in the product posts here.
@router.post("/", response_model=TicketStatusHistoryOut, dependencies=[Depends(require_admin)])
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
    current_user: Profile = Depends(get_current_user),
):
    # A ticket_id is required so this can be scoped — without one, any
    # authenticated user could previously pull every ticket's status
    # history fleet-wide, leaking cross-warehouse ticket activity.
    if not ticket_id:
        raise HTTPException(status_code=400, detail="ticket_id is required")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or not _can_view_ticket(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket not found")

    return (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket_id)
        .order_by(TicketStatusHistory.created_at.desc())
        .all()
    )