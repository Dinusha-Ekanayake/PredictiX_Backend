from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user
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
)

from fastapi import HTTPException
from app.ai.services.ticket_categorization_service import categorize_ticket_text
from app.schemas.tickets import (
    TicketCategorizationRequest,
    TicketCategorizationResponse,
)

router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.post("/", response_model=TicketOut)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    obj = Ticket(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketOut])
def list_tickets(
    status: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Ticket)
    if status:
        q = q.filter(Ticket.status == status)
    if asset_id:
        q = q.filter(Ticket.asset_id == asset_id)
    return q.order_by(Ticket.created_at.desc()).all()


# ── User (owner-scoped) ticket endpoints ──────────────────────────────────────
# Registered BEFORE "/{ticket_id}" so "/mine" isn't captured as an id.
# Ownership is enforced server-side via the app JWT (get_current_user): a
# non-admin user may only read/modify tickets they created.

def _is_admin(user: Profile) -> bool:
    return (getattr(user, "role", None) or "").lower() == "admin"


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
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return obj


@router.put("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: str, payload: TicketUpdate, db: Session = Depends(get_db)):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj

@router.delete("/{ticket_id}")
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


@router.post(
    "/categorize",
    response_model=TicketCategorizationResponse,
)
def categorize_ticket_endpoint(payload: TicketCategorizationRequest):
    try:
        result = categorize_ticket_text(
            title=payload.title,
            description=payload.description,
        )
        return TicketCategorizationResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to categorize ticket: {exc}",
        ) from exc