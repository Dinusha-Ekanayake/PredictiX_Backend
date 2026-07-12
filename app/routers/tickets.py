from fastapi import APIRouter, Depends, HTTPException, Query
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

router = APIRouter(prefix="/tickets", tags=["Tickets"])

# Supabase enums are lowercase — normalize incoming values
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
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    data = payload.model_dump()
    data["ticket_number"] = _generate_ticket_number(db)
    if data.get("priority"):
        data["priority"] = _normalize_priority(data["priority"])
    if data.get("predicted_priority"):
        data["predicted_priority"] = _normalize_priority(data["predicted_priority"])
    if data.get("predicted_category"):
        data["predicted_category"] = _normalize_category(data["predicted_category"])
    obj = Ticket(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/status-counts", response_model=dict[str, int])
def get_ticket_status_counts(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Aggregate ticket counts by status for dashboards.
    Admins/super_admins see counts for their active warehouse only (same
    scoping as every other admin-facing endpoint — assets, admin-dashboard
    summary, list_tickets_paginated). Users see counts for tickets assigned
    to them or created by them.

    Previously admins saw a fleet-wide (unscoped) total here, which didn't
    match the warehouse-scoped counts shown on the admin dashboard and
    every other admin ticket view — e.g. 228 tickets here vs 208 on the
    dashboard for the same admin.
    """
    counts = {"open": 0, "in-progress": 0, "resolved": 0, "closed": 0}
    q = db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)

    if is_admin_role(current_user):
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            q = q.filter(Ticket.warehouse_id == wh_id)
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

    # Role-based scoping — matches /paginated: admins see every ticket,
    # regular users only ever see tickets they created or are assigned to.
    # This endpoint is what the shared asset-details panel's Tickets tab
    # calls (via ?asset_id=), so without this a regular user opening any
    # asset (including one outside their own warehouse) could read every
    # other employee's ticket titles/descriptions for that asset.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.filter(
            (cast(Ticket.created_by, String) == uid) |
            (cast(Ticket.assigned_to, String) == uid)
        )

    if status:
        q = q.filter(Ticket.status == _normalize_status(status))
    if priority:
        q = q.filter(Ticket.priority == _normalize_priority(priority))
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    if warehouse_id:
        q = q.filter(Ticket.warehouse_id == warehouse_id)
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
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """Paginated ticket list with search, filters and total count.
    Used by the frontend ticket page instead of direct Supabase client calls.
    Admins see all tickets; regular users see only tickets they created or are assigned to.
    """
    from sqlalchemy import or_, cast
    from sqlalchemy import String

    q = db.query(Ticket)

    # Role-based scoping
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.filter(
            (cast(Ticket.created_by, String) == uid) |
            (cast(Ticket.assigned_to, String) == uid)
        )

    if status:
        q = q.filter(Ticket.status == _normalize_status(status))
    if priority:
        q = q.filter(Ticket.priority == _normalize_priority(priority))
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    if warehouse_id:
        q = q.filter(Ticket.warehouse_id == warehouse_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            Ticket.title.ilike(term) | Ticket.description.ilike(term)
        )

    total = q.count()
    rows = q.order_by(Ticket.created_at.desc()).offset(offset).limit(limit).all()

    return {"tickets": [TicketOut.model_validate(t) for t in rows], "total": total}


# ── User (owner-scoped) ticket endpoints ──────────────────────────────────────
# Registered BEFORE "/{ticket_id}" so "/mine" isn't captured as an id.
# Ownership is enforced server-side via the app JWT (get_current_user): a
# non-admin user may only read/modify tickets they created.

def _is_admin(user: Profile) -> bool:
    # Includes super_admin — see app.deps.is_admin_role.
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
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = Ticket(
        asset_id=payload.asset_id,
        title=payload.title,
        description=payload.description or "",
        status="open",
        priority=(payload.priority or "medium").lower(),
        predicted_category=(payload.category or "mechanical").lower(),
        created_by=str(current_user.id),  # forced — cannot be spoofed
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    asset_name = None
    if obj.asset_id:
        asset_name = db.query(Asset.asset_name).filter(Asset.id == obj.asset_id).scalar()
    return _serialize_user_ticket(obj, asset_name)


@router.put("/mine/{ticket_id}", response_model=UserTicketOut)
def update_my_ticket(
    ticket_id: str,
    payload: UserTicketUpdate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _is_admin(current_user) and str(obj.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only edit tickets you created.")

    if payload.title is not None:
        obj.title = payload.title
    if payload.description is not None:
        obj.description = payload.description
    if payload.priority:
        obj.priority = payload.priority.lower()
    if payload.category:
        obj.predicted_category = payload.category.lower()

    db.commit()
    db.refresh(obj)
    asset_name = None
    if obj.asset_id:
        asset_name = db.query(Asset.asset_name).filter(Asset.id == obj.asset_id).scalar()
    return _serialize_user_ticket(obj, asset_name)


@router.delete("/mine/{ticket_id}")
def delete_my_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not _is_admin(current_user) and str(obj.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="You can only delete tickets you created.")
    try:
        _purge_ticket(db, ticket_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Cannot delete ticket: {getattr(exc, 'orig', exc)}")
    return {"message": "Ticket deleted", "id": ticket_id}


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str, db: Session = Depends(get_db), _: object = Depends(get_current_user)):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return obj


@router.put("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, payload: TicketUpdate, db: Session = Depends(get_db), current_user: object = Depends(get_current_user)):
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can update tickets")
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updates = payload.model_dump(exclude_unset=True)
    old_status = obj.status

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
        )
        db.add(history)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{ticket_id}", dependencies=[Depends(require_admin)])
def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """Delete a ticket and clean up its dependent rows in one transaction.

    Child rows (comments, attachments, status history, predictions) are
    deleted; soft references (notifications, prediction_runs, reports) are
    NULLed out. Then the ticket itself is removed. FK violations roll back
    and return 409.
    """
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")

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


@router.post(
    "/categorize",
    response_model=TicketCategorizationResponse,
    dependencies=[Depends(require_user)],
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
    dependencies=[Depends(require_user)],
)
def prioritize_ticket_endpoint(payload: TicketPriorityRequest):
    try:
        priority = predict_ticket_priority(title="", description=payload.text)
        return TicketPriorityResponse(priority=_normalize_priority(priority) or "medium")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to classify ticket priority: {exc}") from exc
