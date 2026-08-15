"""User-role ticket endpoints (`/user/tickets`).

Scope: a logged-in user can list, view, create, update (own) and comment on
maintenance tickets. Status transitions, assignment, deletion and viewing
other users' tickets all live in the admin tickets router and are NOT exposed
here.

Inspired by — but deliberately separate from — ``app/routers/tickets.py`` so
the admin section can keep evolving independently.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import Profile, Ticket
from app.schemas.user_tickets import (
    UserTicketAttachmentOut,
    UserTicketAttachmentCreate,
    UserTicketCommentCreate,
    UserTicketCommentOut,
    UserTicketCreate,
    UserTicketDetail,
    UserTicketHistoryOut,
    UserTicketListResponse,
    UserTicketPreviewRequest,
    UserTicketPreviewResponse,
    UserTicketSummary,
    UserTicketUpdate,
)
from app.services import user_ticket_service as svc
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/user/tickets", tags=["User - Tickets"])


# ---------------------------------------------------------------------------
# Phase 1 — listing & details
# ---------------------------------------------------------------------------


@router.get("", response_model=UserTicketListResponse)
def list_my_tickets(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    priority: Optional[str] = Query(default=None),
    asset_id: Optional[UUID] = Query(default=None),
    search: Optional[str] = Query(
        default=None, description="Substring match on title/description/number"
    ),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tickets the current user created or is assigned to."""
    query = svc.build_user_tickets_query(
        db,
        user_id=current_user.id,
        warehouse_id=getattr(current_user, "warehouse_id", None),
        status=status_filter,
        priority=priority,
        asset_id=asset_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    return UserTicketListResponse(
        items=[UserTicketSummary.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats")
def my_ticket_stats(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authoritative status counts for the current user's OWN tickets (unfiltered).
    Drives the KPI cards so they always reflect true Supabase data regardless of
    the active search/status/priority filter or pagination."""
    return svc.get_user_ticket_status_counts(db, current_user.id)


@router.get("/{ticket_id}", response_model=UserTicketDetail)
def get_my_ticket(
    ticket_id: UUID = Path(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Full ticket detail (comments, attachments, history)."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not svc.user_can_view_ticket(ticket, current_user.id, getattr(current_user, "warehouse_id", None)):
        raise HTTPException(status_code=403, detail="Not allowed to view this ticket")

    comments = svc.fetch_ticket_comments(db, ticket_id)
    attachments = svc.fetch_ticket_attachments(db, ticket_id)
    history = svc.fetch_ticket_history(db, ticket_id)

    detail = UserTicketDetail.model_validate(ticket)
    detail.comments = [UserTicketCommentOut.model_validate(c) for c in comments]
    detail.attachments = [UserTicketAttachmentOut.model_validate(a) for a in attachments]
    detail.history = [UserTicketHistoryOut.model_validate(h) for h in history]
    return detail


# ---------------------------------------------------------------------------
# Phase 2 — create & update
# ---------------------------------------------------------------------------


@router.post(
    "/preview",
    response_model=UserTicketPreviewResponse,
)
def preview_my_ticket_ai(
    payload: UserTicketPreviewRequest,
    current_user: Profile = Depends(get_current_user),  # noqa: ARG001 — auth gate only
    db: Session = Depends(get_db),
):
    """Run the AI models on the ticket draft and return predictions.

    Nothing is written to the DB. The frontend uses this to show suggestions
    in the create dialog so the user can accept / regenerate / discard before
    actually creating the ticket.
    """
    result = svc.preview_user_ticket(
        db,
        title=payload.title,
        description=payload.description,
        asset_id=payload.asset_id,
        priority=payload.priority,
    )
    return UserTicketPreviewResponse(**result)


@router.post(
    "",
    response_model=UserTicketDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_my_ticket(
    payload: UserTicketCreate,
    background_tasks: BackgroundTasks,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new ticket. Auto-generates ticket_number; AI is best-effort."""
    try:
        ticket = svc.create_user_ticket(
            db,
            user_id=current_user.id,
            title=payload.title,
            description=payload.description,
            asset_id=payload.asset_id,
            warehouse_id=payload.warehouse_id,
            priority=payload.priority,
            use_ai=payload.use_ai_predictions,
            preset_predicted_priority=payload.predicted_priority,
            preset_predicted_category=payload.predicted_category,
            preset_ticket_summary=payload.ticket_summary,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Could not create ticket: {exc}")

    background_tasks.add_task(NotificationService.notify_on_new_ticket, db, str(ticket.id))

    detail = UserTicketDetail.model_validate(ticket)
    detail.comments = []
    detail.attachments = []
    detail.history = []
    return detail


@router.put("/{ticket_id}", response_model=UserTicketDetail)
def update_my_ticket(
    payload: UserTicketUpdate,
    background_tasks: BackgroundTasks,
    ticket_id: UUID = Path(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update title / description / priority on a ticket the user owns."""
    ticket = svc.get_owned_ticket_or_none(db, ticket_id, current_user.id)
    if not ticket:
        existing = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Ticket not found")
        raise HTTPException(
            status_code=403, detail="You can only update tickets you created"
        )

    # Record old values
    old_status = ticket.status
    old_priority = ticket.priority
    old_assigned_to = str(ticket.assigned_to) if ticket.assigned_to else None

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updatable fields provided")

    try:
        ticket = svc.update_user_ticket(db, ticket, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    comments = svc.fetch_ticket_comments(db, ticket_id)
    attachments = svc.fetch_ticket_attachments(db, ticket_id)
    history = svc.fetch_ticket_history(db, ticket_id)

    background_tasks.add_task(
        NotificationService.notify_on_ticket_update,
        db,
        str(ticket.id),
        str(current_user.id),
        old_status,
        old_priority,
        old_assigned_to
    )

    detail = UserTicketDetail.model_validate(ticket)
    detail.comments = [UserTicketCommentOut.model_validate(c) for c in comments]
    detail.attachments = [UserTicketAttachmentOut.model_validate(a) for a in attachments]
    detail.history = [UserTicketHistoryOut.model_validate(h) for h in history]
    return detail


# ---------------------------------------------------------------------------
# Phase 3 — comments
# ---------------------------------------------------------------------------


@router.get(
    "/{ticket_id}/comments",
    response_model=list[UserTicketCommentOut],
)
def list_my_ticket_comments(
    ticket_id: UUID = Path(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List public comments on a ticket the user is allowed to view."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not svc.user_can_view_ticket(ticket, current_user.id, getattr(current_user, "warehouse_id", None)):
        raise HTTPException(status_code=403, detail="Not allowed to view this ticket")

    comments = svc.fetch_ticket_comments(db, ticket_id)
    return [UserTicketCommentOut.model_validate(c) for c in comments]


@router.post(
    "/{ticket_id}/comments",
    response_model=UserTicketCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_my_ticket_comment(
    payload: UserTicketCommentCreate,
    ticket_id: UUID = Path(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a public comment on a ticket the user is allowed to view."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not svc.user_can_view_ticket(ticket, current_user.id, getattr(current_user, "warehouse_id", None)):
        raise HTTPException(
            status_code=403, detail="Not allowed to comment on this ticket"
        )

    obj = svc.add_user_comment(
        db,
        ticket_id=ticket_id,
        user_id=current_user.id,
        comment=payload.comment,
    )
    return UserTicketCommentOut.model_validate(obj)


@router.post(
    "/{ticket_id}/attachments",
    response_model=UserTicketAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_my_ticket_attachment(
    payload: UserTicketAttachmentCreate,
    ticket_id: UUID = Path(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an attachment to a ticket the user is allowed to view."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not svc.user_can_view_ticket(ticket, current_user.id, getattr(current_user, "warehouse_id", None)):
        raise HTTPException(
            status_code=403, detail="Not allowed to add attachments to this ticket"
        )

    obj = svc.add_user_attachment(
        db,
        ticket_id=ticket_id,
        user_id=current_user.id,
        file_path=payload.file_path,
        mime_type=payload.mime_type,
        original_filename=payload.original_filename,
    )
    return UserTicketAttachmentOut.model_validate(obj)
