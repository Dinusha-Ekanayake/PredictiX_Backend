from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user, get_current_user, is_admin_role
from app.models import Profile, Ticket, TicketComment
from app.schemas.misc import TicketCommentCreate, TicketCommentOut

router = APIRouter(
    prefix="/ticket-comments",
    tags=["Ticket Comments"],
    dependencies=[Depends(require_user)],
)


def _can_view_ticket(ticket: Ticket, current_user: Profile) -> bool:
    """Same rule as tickets.py's get_ticket/list scoping: everyone can
    view (and comment on) any ticket in their own warehouse; users also
    keep visibility into tickets they created or are assigned to outside
    their warehouse. Comment/edit rights on the comment itself stay
    narrower, see delete_ticket_comment."""
    if is_admin_role(current_user):
        return True
    uid = str(getattr(current_user, "id", ""))
    user_wh_id = getattr(current_user, "warehouse_id", None)
    if user_wh_id is not None and str(ticket.warehouse_id) == str(user_wh_id):
        return True
    return str(ticket.created_by) == uid or str(ticket.assigned_to) == uid


@router.post("/", response_model=TicketCommentOut)
def create_ticket_comment(
    payload: TicketCommentCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == payload.ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _can_view_ticket(ticket, current_user):
        raise HTTPException(status_code=404, detail="Ticket not found")

    # user_id is always the authenticated caller, never trust a
    # client-supplied user_id, or any user could post a comment
    # attributed to someone else's identity.
    data = payload.model_dump()
    data["user_id"] = current_user.id

    obj = TicketComment(**data)
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
    current_user: Profile = Depends(get_current_user),
):
    if ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket or not _can_view_ticket(ticket, current_user):
            raise HTTPException(status_code=404, detail="Ticket not found")
        q = db.query(TicketComment).filter(TicketComment.ticket_id == ticket_id)
    elif is_admin_role(current_user):
        q = db.query(TicketComment)
    else:
        # No ticket_id filter and not an admin, scope to comments on
        # tickets this user can actually see (own warehouse, or tickets
        # they created/are assigned to), instead of the whole table.
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        q = db.query(TicketComment).join(Ticket, Ticket.id == TicketComment.ticket_id)
        if user_wh_id is not None:
            q = q.filter(
                (Ticket.warehouse_id == user_wh_id) |
                (Ticket.created_by == uid) |
                (Ticket.assigned_to == uid)
            )
        else:
            q = q.filter((Ticket.created_by == uid) | (Ticket.assigned_to == uid))
    return q.order_by(TicketComment.created_at.asc()).offset(offset).limit(limit).all()


@router.delete("/{comment_id}")
def delete_ticket_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(TicketComment).filter(TicketComment.id == comment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Comment not found")
    if not is_admin_role(current_user) and str(obj.user_id) != str(getattr(current_user, "id", "")):
        raise HTTPException(status_code=403, detail="You can only delete your own comments.")
    db.delete(obj)
    db.commit()
    return {"message": "Comment deleted"}
