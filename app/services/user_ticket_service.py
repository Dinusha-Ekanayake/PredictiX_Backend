"""Business logic for the user-role ticket section.

Keeps the router thin by centralising:
    * ticket number generation (TKT-YYYY-NNNN)
    * ownership checks
    * AI prediction integration (priority + summary) with soft-fail semantics
    * the filter/sort/paginate query for listing
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketStatusHistory,
)

# AI services, imported lazily inside helpers so a missing HF token doesn't
# prevent the rest of the user-ticket section from importing.


# ---------------------------------------------------------------------------
# Enum normalisation. Postgres rejects values outside the declared labels,
# so AI predictions go through these guards before we set them on a Ticket.
# ---------------------------------------------------------------------------

ALLOWED_PRIORITIES = {"low", "medium", "high"}
ALLOWED_CATEGORIES = {"electrical", "mechanical", "software"}


def _normalize_priority(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    # Map common synonyms / out-of-domain labels to the closest in-domain.
    if v in {"critical", "urgent", "severe"}:
        v = "high"
    return v if v in ALLOWED_PRIORITIES else None


def _priority_label(value: object) -> Optional[str]:
    """Accept both the current string priority output and older dict shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return (
            value.get("predicted_label")
            or value.get("priority")
            or value.get("label")
        )
    return None


def _normalize_category(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    return v if v in ALLOWED_CATEGORIES else None


# ---------------------------------------------------------------------------
# Ticket number generation
# ---------------------------------------------------------------------------

TICKET_NUMBER_PREFIX = "TKT"


def generate_ticket_number(db: Session, *, now: Optional[datetime] = None) -> str:
    """Generate the next ticket number in the form ``TKT-YYYY-NNNN``.

    NNNN is the per-year sequence: count of tickets already opened this year
    plus one, zero-padded to four digits. Collisions are rare in practice; if
    the DB has a unique constraint on ``ticket_number`` the caller can retry.
    """
    now = now or datetime.now(timezone.utc)
    year = now.year
    year_prefix = f"{TICKET_NUMBER_PREFIX}-{year}-"

    count_this_year = (
        db.query(Ticket)
        .filter(Ticket.ticket_number.like(f"{year_prefix}%"))
        .count()
    )
    next_seq = count_this_year + 1
    return f"{year_prefix}{next_seq:04d}"


# ---------------------------------------------------------------------------
# Ownership / authorization helpers
# ---------------------------------------------------------------------------


def get_owned_ticket_or_none(
    db: Session, ticket_id: UUID, user_id: UUID
) -> Optional[Ticket]:
    """Return the ticket only if it was created by ``user_id``, else None."""
    return (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id, Ticket.created_by == user_id)
        .first()
    )


def user_can_view_ticket(
    ticket: Ticket, user_id: UUID, warehouse_id: Optional[UUID] = None
) -> bool:
    """Whether a user may view (and comment on) a ticket.

    The warehouse is a hard boundary: a user sees tickets belonging to their
    own warehouse, and nothing outside it. Being the creator or assignee does
    not grant access across that boundary: if it did, a ticket raised before
    someone transferred sites, or one moved to another warehouse, would stay
    readable from the wrong site indefinitely.

    Within the caller's own warehouse every ticket is viewable, which is what
    makes colleagues able to pick up and comment on each other's work. What the
    *list* surfaces is a separate, narrower question, see
    :func:`build_user_tickets_query`, which returns only the caller's own.

    ``warehouse_id`` may be ``None`` when the caller's warehouse is unknown
    (a profile with no site, or a caller that does not pass one). There is no
    boundary to enforce in that case, so it falls back to ownership rather than
    denying outright, which would lock a user out of a ticket that is
    demonstrably theirs.

    Editing remains owner-only regardless, see :func:`get_owned_ticket_or_none`.
    """
    if warehouse_id is not None:
        return ticket.warehouse_id == warehouse_id
    return ticket.created_by == user_id or ticket.assigned_to == user_id


# ---------------------------------------------------------------------------
# Listing query
# ---------------------------------------------------------------------------

SORTABLE_FIELDS = {
    "created_at": Ticket.created_at,
    "updated_at": Ticket.updated_at,
    "priority": Ticket.priority,
    "status": Ticket.status,
    "ticket_number": Ticket.ticket_number,
    "title": Ticket.title,
    "name": Ticket.title,
}


def build_user_tickets_query(
    db: Session,
    *,
    user_id: UUID,
    warehouse_id: Optional[UUID] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    asset_id: Optional[UUID] = None,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    """Build a SQLAlchemy query for the tickets that belong to this user, ones they created or are assigned to.

    Ownership is the only filter. ORing in every ticket in the user's
    warehouse would put the list at odds with everything around it: the page
    is titled "My Tickets", the endpoints are ``list_my_tickets`` /
    ``my_ticket_stats``, and the KPI cards above the list come from
    :func:`get_user_ticket_status_counts`, which is owner-scoped. A user who
    has never raised or been assigned a ticket would then see cards reading 0
    above a long list, the same screen disagreeing with itself.

    ``warehouse_id`` stays in the signature because callers pass it and an
    "all warehouse tickets" view would need it, but it does not widen
    visibility here.

    Note this governs the *list* only. :func:`user_can_view_ticket` still
    permits opening any ticket in your own warehouse by id, which is a
    deliberately separate question from what the list shows you. Editing
    remains owner-only via :func:`get_owned_ticket_or_none`.
    """
    q = db.query(Ticket).filter(
        or_(Ticket.created_by == user_id, Ticket.assigned_to == user_id)
    )

    if status:
        q = q.filter(Ticket.status == status)
    if priority:
        q = q.filter(
            or_(Ticket.priority == priority, Ticket.final_priority == priority)
        )
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    if search:
        like = f"%{search}%"
        from app.models import Profile
        assigned_user_exists = db.query(Profile.id).filter(
            (Profile.id == Ticket.assigned_to) &
            (Profile.full_name.ilike(like))
        ).exists()
        q = q.filter(
            or_(
                Ticket.title.ilike(like),
                Ticket.description.ilike(like),
                Ticket.ticket_number.ilike(like),
                assigned_user_exists,
            )
        )
    if date_from:
        q = q.filter(Ticket.created_at >= date_from)
    if date_to:
        q = q.filter(Ticket.created_at <= date_to)

    sort_col = SORTABLE_FIELDS.get(sort_by, Ticket.created_at)
    if sort_dir.lower() == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    return q


def get_user_ticket_status_counts(db: Session, user_id: UUID) -> dict[str, int]:
    """Authoritative status counts for the user's OWN tickets, computed directly
    in Postgres (GROUP BY status) and independent of any list filter/pagination.
    These are the numbers the KPI cards should display.

    "Own" must mean the same thing here as in
    :func:`build_user_tickets_query`: created **or** assigned. Counting only
    ``created_by`` is wrong for anyone assigned work without raising it
    themselves, and shows a mechanic nine assigned tickets under cards reading
    zero. Drivers raise tickets and technicians receive them, so that
    describes most of the
    maintenance staff.
    """
    rows = (
        db.query(Ticket.status, func.count(Ticket.id))
        .filter(or_(Ticket.created_by == user_id, Ticket.assigned_to == user_id))
        .group_by(Ticket.status)
        .all()
    )
    counts = {str(s): int(c) for s, c in rows}
    return {
        "open":        counts.get("open", 0),
        "in_progress": counts.get("in_progress", 0),
        "pending":     counts.get("pending", 0),
        "resolved":    counts.get("resolved", 0),
        "closed":      counts.get("closed", 0),
        "cancelled":   counts.get("cancelled", 0),
        "total":       sum(counts.values()),
    }


# ---------------------------------------------------------------------------
# Related-row fetchers (used by detail endpoint)
# ---------------------------------------------------------------------------


def fetch_ticket_comments(
    db: Session, ticket_id: UUID, *, include_internal: bool = False
) -> list[TicketComment]:
    q = db.query(TicketComment).filter(TicketComment.ticket_id == ticket_id)
    if not include_internal:
        q = q.filter(TicketComment.is_internal.is_(False))
    return q.order_by(TicketComment.created_at.asc()).all()


def fetch_ticket_attachments(db: Session, ticket_id: UUID) -> list[TicketAttachment]:
    return (
        db.query(TicketAttachment)
        .filter(TicketAttachment.ticket_id == ticket_id)
        .order_by(TicketAttachment.created_at.asc())
        .all()
    )


def fetch_ticket_history(db: Session, ticket_id: UUID) -> list[TicketStatusHistory]:
    return (
        db.query(TicketStatusHistory)
        .filter(TicketStatusHistory.ticket_id == ticket_id)
        .order_by(TicketStatusHistory.created_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# AI integration (soft-fail)
# ---------------------------------------------------------------------------


def _safe_log(prefix: str, exc: Exception) -> None:
    print(f"[USER-TICKETS][{prefix}] {type(exc).__name__}: {exc}", flush=True)


def predict_priority_safely(title: str, description: str) -> Optional[object]:
    """Run the priority classifier. Returns None on any failure."""
    try:
        from app.ai.services.ticket_priority_service import predict_ticket_priority

        return predict_ticket_priority(title=title, description=description)
    except Exception as exc:  # noqa: BLE001, AI is best-effort
        _safe_log("priority", exc)
        return None


def predict_category_safely(title: str, description: str) -> Optional[dict]:
    """Run the category classifier. Returns None on any failure."""
    try:
        from app.ai.services.ticket_categorization_service import (
            categorize_ticket_text,
        )

        return categorize_ticket_text(title=title, description=description)
    except Exception as exc:  # noqa: BLE001
        _safe_log("category", exc)
        return None


def generate_summary_safely(
    db: Session,
    *,
    title: str,
    description: str,
    asset_id: Optional[UUID],
    category: Optional[str],
    priority: Optional[str],
) -> Optional[str]:
    """Generate a ticket summary using the Seq2Seq model. None on failure."""
    try:
        from app.ai.services.ticket_summary_service import (
            build_ticket_summary_input,
            generate_ticket_summary,
        )

        asset_name: Optional[str] = None
        asset_code: Optional[str] = None
        if asset_id is not None:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if asset is not None:
                asset_name = asset.asset_name
                asset_code = asset.asset_code

        text = build_ticket_summary_input(
            title=title,
            description=description,
            asset_name=asset_name,
            asset_code=asset_code,
            category=category,
            priority=priority,
        )
        return generate_ticket_summary(text)
    except Exception as exc:  # noqa: BLE001
        _safe_log("summary", exc)
        return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def preview_user_ticket(
    db: Session,
    *,
    title: str,
    description: str,
    asset_id: Optional[UUID],
    priority: Optional[str],
) -> dict:
    """Run the three AI models and return their outputs without saving."""
    out: dict = {
        "predicted_priority": None,
        "predicted_category": None,
        "ticket_summary": None,
        "errors": {},
    }

    try:
        from app.ai.services.ticket_priority_service import predict_ticket_priority
        # predict_ticket_priority returns a plain string ("High"/"Medium"/"Low").
        result = predict_ticket_priority(title=title, description=description)
        out["predicted_priority"] = _normalize_priority(result)
    except Exception as exc:  # noqa: BLE001
        _safe_log("preview.priority", exc)
        out["errors"]["priority"] = str(exc)

    try:
        from app.ai.services.ticket_categorization_service import categorize_ticket_text
        result = categorize_ticket_text(title=title, description=description)
        out["predicted_category"] = _normalize_category(result["predicted_label"])
    except Exception as exc:  # noqa: BLE001
        _safe_log("preview.category", exc)
        out["errors"]["category"] = str(exc)

    try:
        from app.ai.services.ticket_summary_service import (
            build_ticket_summary_input,
            generate_ticket_summary,
        )
        asset_name: Optional[str] = None
        asset_code: Optional[str] = None
        if asset_id is not None:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if asset is not None:
                asset_name = asset.asset_name
                asset_code = asset.asset_code

        text = build_ticket_summary_input(
            title=title,
            description=description,
            asset_name=asset_name,
            asset_code=asset_code,
            category=out["predicted_category"],
            priority=priority or out["predicted_priority"],
        )
        out["ticket_summary"] = generate_ticket_summary(text)
    except Exception as exc:  # noqa: BLE001
        _safe_log("preview.summary", exc)
        out["errors"]["summary"] = str(exc)

    return out


def create_user_ticket(
    db: Session,
    *,
    user_id: UUID,
    title: str,
    description: str,
    asset_id: Optional[UUID],
    warehouse_id: Optional[UUID],
    priority: Optional[str],
    use_ai: bool,
    # Pre-computed AI fields (from a previous /preview call). Used only when
    # `use_ai=False`, so the user can accept the previewed values without
    # forcing the backend to re-run the models.
    preset_predicted_priority: Optional[str] = None,
    preset_predicted_category: Optional[str] = None,
    preset_ticket_summary: Optional[str] = None,
) -> Ticket:
    """Create a new ticket on behalf of the user, optionally enriching with AI."""
    predicted_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    ticket_summary: Optional[str] = None

    if use_ai:
        priority_result = predict_priority_safely(title, description)
        if priority_result:
            # predict_priority_safely returns a plain string ("High"/"Medium"/"Low").
            predicted_priority = _normalize_priority(priority_result)

        category_result = predict_category_safely(title, description)
        if category_result:
            predicted_category = _normalize_category(category_result["predicted_label"])

        ticket_summary = generate_summary_safely(
            db,
            title=title,
            description=description,
            asset_id=asset_id,
            category=predicted_category,
            priority=priority or predicted_priority,
        )
    else:
        # Honor preview values the user already accepted.
        predicted_priority = _normalize_priority(preset_predicted_priority)
        predicted_category = _normalize_category(preset_predicted_category)
        ticket_summary = preset_ticket_summary

    ticket = Ticket(
        ticket_number=generate_ticket_number(db),
        title=title,
        description=description,
        status="open",
        priority=_normalize_priority(priority),
        predicted_priority=predicted_priority,
        predicted_category=predicted_category,
        ticket_summary=ticket_summary,
        asset_id=asset_id,
        warehouse_id=warehouse_id,
        created_by=user_id,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


# Fields a user is allowed to update on their own tickets.
USER_UPDATABLE_FIELDS: tuple[str, ...] = ("title", "description", "priority")


def update_user_ticket(
    db: Session, ticket: Ticket, updates: dict
) -> Ticket:
    """Apply the whitelisted fields and commit. Caller handles authorization."""
    applied = False
    for field, value in updates.items():
        if field not in USER_UPDATABLE_FIELDS or value is None:
            continue
        # Priority is a Postgres enum, coerce before assignment so an out-of-
        # range value raises here (HTTP 400 via the router) instead of crashing
        # the INSERT/UPDATE with a Postgres DatatypeMismatch.
        if field == "priority":
            normalized = _normalize_priority(value)
            if normalized is None:
                raise ValueError(
                    f"Invalid priority: {value!r}. Allowed: {sorted(ALLOWED_PRIORITIES)}"
                )
            value = normalized
        setattr(ticket, field, value)
        applied = True

    if applied:
        db.commit()
        db.refresh(ticket)
    return ticket


def add_user_comment(
    db: Session, *, ticket_id: UUID, user_id: UUID, comment: str
) -> TicketComment:
    obj = TicketComment(
        ticket_id=ticket_id,
        user_id=user_id,
        comment=comment,
        is_internal=False,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def add_user_attachment(
    db: Session, *, ticket_id: UUID, user_id: UUID, file_path: str, mime_type: Optional[str] = None, original_filename: Optional[str] = None
) -> TicketAttachment:
    obj = TicketAttachment(
        ticket_id=ticket_id,
        file_path=file_path,
        mime_type=mime_type,
        original_filename=original_filename,
        uploaded_by=user_id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
