import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import String, cast, func

from app.deps import get_db, get_current_user, require_admin, require_user, is_admin_role, active_warehouse_id
from app.models import (
    Asset,
    Notification,
    PredictionRun,
    Profile,
    Report,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketPrediction,
    TicketStatusHistory,
)
from app.services.in_app_notification_service import InAppNotificationService
from app.schemas.tickets import (
    TicketCreate,
    TicketUpdate,
    TicketOut,
    UserTicketCreate,
    UserTicketUpdate,
    UserTicketOut,
    TicketCategorizationRequest,
    TicketCategorizationResponse,
    TicketPriorityRequest,
    TicketPriorityResponse,
    TicketPreviewRequest,
    TicketPreviewResponse,
)
from app.ai.services.ticket_categorization_service import categorize_ticket_text
from app.ai.services.ticket_priority_service import predict_ticket_priority
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/tickets", tags=["Tickets"])
log = logging.getLogger(__name__)

# Supabase enums are lowercase, normalize incoming values
VALID_STATUSES = {"open", "in_progress", "pending", "resolved", "closed", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high"}
VALID_CATEGORIES = {"electrical", "mechanical", "software"}


def _normalize_status(v: str | None) -> str | None:
    if v is None:
        return None
    normalized = v.lower().replace(" ", "_")
    if normalized not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{v}'. Valid: {sorted(VALID_STATUSES)}")
    return normalized


def _normalize_priority(v: str | None) -> str | None:
    if v is None:
        return None
    normalized = v.lower()
    if normalized in {"critical", "urgent", "severe"}:
        normalized = "high"
    if normalized not in VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"Invalid priority '{v}'. Valid: {sorted(VALID_PRIORITIES)}")
    return normalized


def _normalize_category(v: str | None) -> str | None:
    if v is None:
        return None
    normalized = v.lower()
    if normalized not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid category '{v}'. Valid: {sorted(VALID_CATEGORIES)}")
    return normalized


def _generate_ticket_number(db: Session) -> str:
    count = db.query(func.count(Ticket.id)).scalar() or 0
    return f"T-{count + 1:04d}"


@router.post("/", response_model=TicketOut)
def create_ticket(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    data = payload.model_dump()
    data["ticket_number"] = _generate_ticket_number(db)
    if data.get("priority"):
        data["priority"] = _normalize_priority(data["priority"])
    if data.get("predicted_priority"):
        data["predicted_priority"] = _normalize_priority(data["predicted_priority"])
    if data.get("predicted_category"):
        data["predicted_category"] = _normalize_category(data["predicted_category"])

    # Tag the ticket with a warehouse so it shows up in warehouse-scoped
    # ticket lists, prefer the linked asset's warehouse (authoritative),
    # falling back to the creating admin's active warehouse. Without this,
    # tickets silently had a NULL warehouse_id and were invisible to the
    # scoped list/status-count endpoints.
    if not data.get("warehouse_id"):
        if data.get("asset_id"):
            data["warehouse_id"] = db.query(Asset.warehouse_id).filter(Asset.id == data["asset_id"]).scalar()
        if not data.get("warehouse_id") and is_admin_role(current_user):
            data["warehouse_id"] = active_warehouse_id(current_user)

    obj = Ticket(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    if obj.assigned_to:
        _notify_ticket_assignment(db, obj)

    background_tasks.add_task(NotificationService.notify_on_new_ticket, db, str(obj.id))
    return obj


def _notify_ticket_assignment(db: Session, ticket: Ticket) -> None:
    """Best-effort in-app notification to a newly assigned ticket user.
    Never allowed to break the ticket create/update flow it's called from."""
    try:
        InAppNotificationService.notify_user(
            db,
            user_id=str(ticket.assigned_to),
            title="Ticket assigned to you",
            message=f"{ticket.ticket_number}: {ticket.title}",
            priority=ticket.priority or "medium",
            notification_type="ticket_updated",
            link_url=f"/admin/tickets?ticket_id={ticket.id}",
        )
    except Exception:
        log.exception("Failed to send ticket assignment notification for %s", ticket.id)


@router.get("/status-counts", response_model=dict[str, int])
def get_ticket_status_counts(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Aggregate ticket counts by status for dashboards.
    Everyone (users, admins, super_admins) sees counts scoped to their own
    warehouse, same visibility as list_tickets/list_tickets_paginated/
    get_ticket. Users additionally see tickets assigned to or created by
    them even if those fall outside their own warehouse.
    """
    counts = {"open": 0, "in-progress": 0, "resolved": 0, "closed": 0}
    q = db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)

    if is_admin_role(current_user):
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            # Tickets with no warehouse_id (orphaned, e.g. created without
            # an asset) stay visible to every admin rather than vanishing
            # from everyone's counts. Matches list_tickets/list_tickets_paginated.
            q = q.filter((Ticket.warehouse_id == wh_id) | (Ticket.warehouse_id.is_(None)))
    else:
        user_wh_id = getattr(current_user, "warehouse_id", None)
        if user_wh_id:
            q = q.filter(
                (Ticket.warehouse_id == user_wh_id) |
                (Ticket.assigned_to == current_user.id) |
                (Ticket.created_by == current_user.id)
            )
        else:
            q = q.filter((Ticket.assigned_to == current_user.id) | (Ticket.created_by == current_user.id))

    rows = q.all()

    for status, count in rows:
        if status in ("open", "pending"):
            counts["open"] += count
        elif status == "in_progress":
            counts["in-progress"] += count
        elif status == "resolved":
            counts["resolved"] += count
        elif status == "closed":
            counts["closed"] += count

    return counts

@router.get("/", response_model=list[TicketOut])
def list_tickets(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    q = db.query(Ticket)

    # Role-based scoping. Matches /paginated and get_ticket: everyone
    # (users, admins, super_admins) can see every ticket in their own
    # warehouse and can comment on it; only owners/admins may edit one
    # (enforced separately in update_my_ticket/update_ticket). Users also
    # see tickets assigned to or created by them even outside their
    # warehouse (e.g. a cross-warehouse assignment).
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        if user_wh_id:
            q = q.filter(
                (Ticket.warehouse_id == user_wh_id) |
                (cast(Ticket.created_by, String) == uid) |
                (cast(Ticket.assigned_to, String) == uid)
            )
        else:
            q = q.filter(
                (cast(Ticket.created_by, String) == uid) |
                (cast(Ticket.assigned_to, String) == uid)
            )
    else:
        # Pin to the admin's active warehouse, overriding any
        # client-supplied warehouse_id, same pattern as departments.py.
        # Tickets with no warehouse_id (orphaned) stay visible to every
        # admin rather than becoming invisible to everyone.
        scoped_wh = active_warehouse_id(current_user)
        if scoped_wh:
            warehouse_id = scoped_wh

    if status:
        q = q.filter(Ticket.status == _normalize_status(status))
    if priority:
        q = q.filter(Ticket.priority == _normalize_priority(priority))
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    if warehouse_id:
        q = q.filter((Ticket.warehouse_id == warehouse_id) | (Ticket.warehouse_id.is_(None)))
    if assigned_to:
        q = q.filter(Ticket.assigned_to == assigned_to)
    return q.order_by(Ticket.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/paginated")
def list_tickets_paginated(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    search: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """Paginated ticket list with search, filters and total count.
    Used by the frontend ticket page instead of direct Supabase client calls.
    Everyone sees every ticket in their own warehouse (see list_tickets for
    the full scoping rationale); only owners/admins may edit one.
    """
    from sqlalchemy import or_, cast
    from sqlalchemy import String

    q = db.query(Ticket)

    # Role-based scoping, see list_tickets.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        if user_wh_id:
            q = q.filter(
                (Ticket.warehouse_id == user_wh_id) |
                (cast(Ticket.created_by, String) == uid) |
                (cast(Ticket.assigned_to, String) == uid)
            )
        else:
            q = q.filter(
                (cast(Ticket.created_by, String) == uid) |
                (cast(Ticket.assigned_to, String) == uid)
            )
    else:
        # Pin to the admin's active warehouse, overriding any
        # client-supplied warehouse_id, same pattern as departments.py.
        # Tickets with no warehouse_id (orphaned) stay visible to every
        # admin rather than becoming invisible to everyone.
        scoped_wh = active_warehouse_id(current_user)
        if scoped_wh:
            warehouse_id = scoped_wh

    if status:
        q = q.filter(Ticket.status == _normalize_status(status))
    if priority:
        q = q.filter(Ticket.priority == _normalize_priority(priority))
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    if warehouse_id:
        q = q.filter((Ticket.warehouse_id == warehouse_id) | (Ticket.warehouse_id.is_(None)))
    if search and search.strip():
        term = f"%{search.strip()}%"
        from app.models import Profile
        assigned_user_exists = db.query(Profile.id).filter(
            (Profile.id == Ticket.assigned_to) &
            (Profile.full_name.ilike(term))
        ).exists()
        q = q.filter(
            Ticket.title.ilike(term) |
            Ticket.description.ilike(term) |
            Ticket.ticket_number.ilike(term) |
            assigned_user_exists
        )

    total = q.count()

    # Sort results
    sort_col = Ticket.created_at
    if sort_by:
        s_by = sort_by.lower()
        if s_by in ("title", "name"):
            sort_col = Ticket.title
        elif s_by == "priority":
            sort_col = Ticket.priority
        elif s_by == "status":
            sort_col = Ticket.status
        elif s_by == "ticket_number":
            sort_col = Ticket.ticket_number
        elif s_by == "updated_at":
            sort_col = Ticket.updated_at

    if sort_dir.lower() == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    rows = q.offset(offset).limit(limit).all()

    return {"tickets": [TicketOut.model_validate(t) for t in rows], "total": total}


# ── User (owner-scoped) ticket endpoints ──────────────────────────────────────
# Registered BEFORE "/{ticket_id}" so "/mine" isn't captured as an id.
# Edit/delete rights are enforced server-side via the app JWT
# (get_current_user): only the ticket's creator or an admin may modify it.

def _is_admin(user: Profile) -> bool:
    # Includes super_admin, see app.deps.is_admin_role.
    return is_admin_role(user)


def _serialize_user_ticket(t: Ticket, asset_name: str | None) -> dict:
    return {
        "id": t.id,
        "ticket_number": t.ticket_number,
        "asset_id": t.asset_id,
        "asset_name": asset_name,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "priority": t.priority,
        "predicted_category": t.predicted_category,
        "final_category": t.final_category,
        "created_by": t.created_by,
        "assigned_to": t.assigned_to,
        "opened_at": t.opened_at,
        "created_at": t.created_at,
    }


def _purge_ticket(db: Session, ticket_id: str) -> None:
    """Delete a ticket's child rows + null soft refs, then the ticket."""
    db.query(TicketComment).filter(TicketComment.ticket_id == ticket_id).delete(synchronize_session=False)
    db.query(TicketAttachment).filter(TicketAttachment.ticket_id == ticket_id).delete(synchronize_session=False)
    db.query(TicketStatusHistory).filter(TicketStatusHistory.ticket_id == ticket_id).delete(synchronize_session=False)
    db.query(TicketPrediction).filter(TicketPrediction.ticket_id == ticket_id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.related_ticket_id == ticket_id).update({Notification.related_ticket_id: None}, synchronize_session=False)
    db.query(PredictionRun).filter(PredictionRun.ticket_id == ticket_id).update({PredictionRun.ticket_id: None}, synchronize_session=False)
    db.query(Report).filter(Report.ticket_id == ticket_id).update({Report.ticket_id: None}, synchronize_session=False)
    db.query(Ticket).filter(Ticket.id == ticket_id).delete(synchronize_session=False)


@router.get("/mine", response_model=list[UserTicketOut])
def list_my_tickets(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    query = db.query(Ticket).filter(Ticket.created_by == str(current_user.id))
    if status and status != "all":
        query = query.filter(Ticket.status == status)
    if priority and priority != "all":
        query = query.filter(Ticket.priority == priority)
    if q:
        like = f"%{q}%"
        query = query.filter((Ticket.title.ilike(like)) | (Ticket.description.ilike(like)))

    rows = query.order_by(Ticket.created_at.desc()).offset(offset).limit(limit).all()

    # Batch-resolve asset names (no N+1).
    asset_ids = {r.asset_id for r in rows if r.asset_id}
    name_map: dict = {}
    if asset_ids:
        for aid, aname in db.query(Asset.id, Asset.asset_name).filter(Asset.id.in_(asset_ids)).all():
            name_map[aid] = aname

    return [_serialize_user_ticket(r, name_map.get(r.asset_id)) for r in rows]


@router.post("/mine", response_model=UserTicketOut)
def create_my_ticket(
    payload: UserTicketCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    warehouse_id = None
    if payload.asset_id:
        warehouse_id = db.query(Asset.warehouse_id).filter(Asset.id == payload.asset_id).scalar()
    if not warehouse_id:
        warehouse_id = getattr(current_user, "warehouse_id", None)

    obj = Ticket(
        asset_id=payload.asset_id,
        warehouse_id=warehouse_id,
        title=payload.title,
        description=payload.description or "",
        status="open",
        priority=_normalize_priority(payload.priority) or "medium",
        predicted_category=_normalize_category(payload.category) or "mechanical",
        created_by=str(current_user.id),  # forced, cannot be spoofed
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    asset_name = None
    if obj.asset_id:
        asset_name = db.query(Asset.asset_name).filter(Asset.id == obj.asset_id).scalar()
    background_tasks.add_task(NotificationService.notify_on_new_ticket, db, str(obj.id))
    return _serialize_user_ticket(obj, asset_name)


@router.put("/mine/{ticket_id}", response_model=UserTicketOut)
def update_my_ticket(
    ticket_id: str,
    payload: UserTicketUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _is_admin(current_user) and str(obj.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only edit tickets you created.")

    # Record old values
    old_status = obj.status
    old_priority = obj.priority
    old_assigned_to = str(obj.assigned_to) if obj.assigned_to else None

    if payload.title is not None:
        obj.title = payload.title
    if payload.description is not None:
        obj.description = payload.description
    if payload.priority:
        obj.priority = _normalize_priority(payload.priority)
    if payload.category:
        obj.predicted_category = _normalize_category(payload.category)

    db.commit()
    db.refresh(obj)
    asset_name = None
    if obj.asset_id:
        asset_name = db.query(Asset.asset_name).filter(Asset.id == obj.asset_id).scalar()

    background_tasks.add_task(
        NotificationService.notify_on_ticket_update,
        db,
        str(obj.id),
        str(current_user.id),
        old_status,
        old_priority,
        old_assigned_to
    )

    return _serialize_user_ticket(obj, asset_name)


@router.delete("/mine/{ticket_id}")
def delete_my_ticket(
    ticket_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _is_admin(current_user) and str(obj.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only delete tickets you created.")
    
    # Gather details for deletion notification before purging
    ticket_number = obj.ticket_number
    title = obj.title
    
    creator = db.query(Profile).filter(Profile.id == obj.created_by).first()
    creator_email = creator.email if creator else None
    
    assignee_email = None
    if obj.assigned_to:
        assignee = db.query(Profile).filter(Profile.id == obj.assigned_to).first()
        assignee_email = assignee.email if assignee else None
        
    admin_emails = NotificationService._admin_emails_for_warehouse(db, obj.warehouse_id)
    deleter_name = getattr(current_user, "full_name", "User")

    try:
        _purge_ticket(db, ticket_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Cannot delete ticket: {getattr(exc, 'orig', exc)}")
        
    background_tasks.add_task(
        NotificationService.notify_on_ticket_delete,
        ticket_number,
        title,
        creator_email,
        assignee_email,
        deleter_name,
        admin_emails
    )
    return {"message": "Ticket deleted", "id": ticket_id}


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str, db: Session = Depends(get_db), current_user: Profile = Depends(get_current_user)):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Same scoping as list_tickets/list_tickets_paginated: everyone can read
    # (and comment on) any ticket in their own warehouse; only owners/admins
    # may edit one (enforced in update_my_ticket/update_ticket). Without
    # this, any authenticated user could read any ticket by
    # guessing/incrementing its id.
    if not is_admin_role(current_user):
        uid = str(current_user.id)
        user_wh_id = getattr(current_user, "warehouse_id", None)
        same_warehouse = user_wh_id is not None and str(obj.warehouse_id) == str(user_wh_id)
        involved = str(obj.created_by) == uid or str(obj.assigned_to) == uid
        if not same_warehouse and not involved:
            raise HTTPException(status_code=404, detail="Ticket not found")
    return obj


@router.put("/{ticket_id}", response_model=TicketOut)
def update_ticket(
    ticket_id: str,
    payload: TicketUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can update tickets")
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updates = payload.model_dump(exclude_unset=True)
    old_status = obj.status
    old_priority = obj.priority
    old_assigned_to = str(obj.assigned_to) if obj.assigned_to else None

    # normalize enum fields
    if "status" in updates and updates["status"]:
        updates["status"] = _normalize_status(updates["status"])
    if "priority" in updates and updates["priority"]:
        updates["priority"] = _normalize_priority(updates["priority"])
    if "final_priority" in updates and updates["final_priority"]:
        updates["final_priority"] = _normalize_priority(updates["final_priority"])
    if "predicted_priority" in updates and updates["predicted_priority"]:
        updates["predicted_priority"] = _normalize_priority(updates["predicted_priority"])
    if "final_category" in updates and updates["final_category"]:
        updates["final_category"] = _normalize_category(updates["final_category"])
    if "predicted_category" in updates and updates["predicted_category"]:
        updates["predicted_category"] = _normalize_category(updates["predicted_category"])

    for key, value in updates.items():
        setattr(obj, key, value)

    # auto-log status transition
    new_status = updates.get("status")
    if new_status and new_status != old_status:
        history = TicketStatusHistory(
            ticket_id=obj.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=getattr(current_user, "id", None),
        )
        db.add(history)

        # Stamp the lifecycle timestamps the tickets table carries for this
        # purpose. Without these, resolved_at and closed_at stay null forever
        # and any resolution-time metric has no data to work from. Only set on
        # first entry into the state, so reopening and resolving again keeps
        # the original resolution time rather than overwriting it.
        now = datetime.now(timezone.utc)
        if new_status == "resolved" and obj.resolved_at is None:
            obj.resolved_at = now
        elif new_status == "closed" and obj.closed_at is None:
            obj.closed_at = now

    db.commit()
    db.refresh(obj)
    new_assigned_to = updates.get("assigned_to")
    if new_assigned_to and str(new_assigned_to) != str(old_assigned_to or ""):
        _notify_ticket_assignment(db, obj)
    background_tasks.add_task(
        NotificationService.notify_on_ticket_update,
        db,
        str(obj.id),
        str(getattr(current_user, "id", "")),
        old_status,
        old_priority,
        old_assigned_to
    )

    return obj


@router.delete("/{ticket_id}")
def delete_ticket(
    ticket_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(require_admin),
):
    """Delete a ticket and clean up its dependent rows in one transaction.

    Child rows (comments, attachments, status history, predictions) are
    deleted; soft references (notifications, prediction_runs, reports) are
    NULLed out. Then the ticket itself is removed. FK violations roll back
    and return 409.
    """
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Gather details for deletion notification before purging
    ticket_number = obj.ticket_number
    title = obj.title
    
    creator = db.query(Profile).filter(Profile.id == obj.created_by).first()
    creator_email = creator.email if creator else None
    
    assignee_email = None
    if obj.assigned_to:
        assignee = db.query(Profile).filter(Profile.id == obj.assigned_to).first()
        assignee_email = assignee.email if assignee else None
        
    admin_emails = NotificationService._admin_emails_for_warehouse(db, obj.warehouse_id)
    deleter_name = getattr(current_user, "full_name", "Admin")

    try:
        # Delete owned child rows.
        db.query(TicketComment).filter(TicketComment.ticket_id == ticket_id).delete(
            synchronize_session=False
        )
        db.query(TicketAttachment).filter(
            TicketAttachment.ticket_id == ticket_id
        ).delete(synchronize_session=False)
        db.query(TicketStatusHistory).filter(
            TicketStatusHistory.ticket_id == ticket_id
        ).delete(synchronize_session=False)
        db.query(TicketPrediction).filter(
            TicketPrediction.ticket_id == ticket_id
        ).delete(synchronize_session=False)

        # NULL out soft references.
        db.query(Notification).filter(
            Notification.related_ticket_id == ticket_id
        ).update({Notification.related_ticket_id: None}, synchronize_session=False)
        db.query(PredictionRun).filter(PredictionRun.ticket_id == ticket_id).update(
            {PredictionRun.ticket_id: None}, synchronize_session=False
        )
        db.query(Report).filter(Report.ticket_id == ticket_id).update(
            {Report.ticket_id: None}, synchronize_session=False
        )

        db.delete(obj)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        orig = getattr(exc, "orig", None)
        detail = str(orig) if orig else str(exc)
        raise HTTPException(status_code=409, detail=f"Cannot delete ticket: {detail}")

    background_tasks.add_task(
        NotificationService.notify_on_ticket_delete,
        ticket_number,
        title,
        creator_email,
        assignee_email,
        deleter_name,
        admin_emails
    )
    return {"message": "Ticket deleted", "id": ticket_id}


@router.post("/preview", response_model=TicketPreviewResponse)
def preview_ticket(payload: TicketPreviewRequest, _: object = Depends(get_current_user)):
    """Run category + priority AI without saving. Used by the create dialog."""
    errors: dict[str, str] = {}
    predicted_category: str | None = None
    predicted_priority: str | None = None

    try:
        cat = categorize_ticket_text(title=payload.title, description=payload.description)
        predicted_category = (cat.get("predicted_label") or "").lower() or None
    except Exception as exc:
        errors["category"] = str(exc)

    try:
        pri = predict_ticket_priority(title=payload.title, description=payload.description)
        predicted_priority = _normalize_priority(pri) if pri else None
    except Exception as exc:
        errors["priority"] = str(exc)

    return TicketPreviewResponse(
        predicted_category=predicted_category,
        predicted_priority=predicted_priority,
        errors=errors,
    )


# Admin-gated, not user-gated: this forwards free text straight to a Hugging
# Face Space, so any account could use it as an unmetered proxy to that Space
# and exhaust it for the ticket-creation path that actually needs it. Ticket
# creation is unaffected, it calls categorize_ticket_text() directly (see
# create_ticket above) rather than going through this route, and no frontend
# code calls this endpoint at all.
@router.post(
    "/categorize",
    response_model=TicketCategorizationResponse,
    dependencies=[Depends(require_admin)],
)
def categorize_ticket_endpoint(payload: TicketCategorizationRequest):
    try:
        result = categorize_ticket_text(title=payload.title, description=payload.description)
        return TicketCategorizationResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to categorize ticket: {exc}") from exc


@router.post(
    "/prioritize",
    response_model=TicketPriorityResponse,
    summary="Classify ticket priority",
    description=(
        "Sends ticket text to the AroshN/priority_classif_xgb XGBoost model on Hugging Face "
        "and returns a single priority label (e.g. Low, Medium, High, Critical)."
    ),
    dependencies=[Depends(require_admin)],
)
def prioritize_ticket_endpoint(payload: TicketPriorityRequest):
    try:
        priority = predict_ticket_priority(title="", description=payload.text)
        return TicketPriorityResponse(priority=_normalize_priority(priority) or "medium")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to classify ticket priority: {exc}") from exc
