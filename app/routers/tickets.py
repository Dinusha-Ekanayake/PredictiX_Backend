from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.deps import get_db
from app.models import Ticket, TicketStatusHistory
from app.schemas.tickets import TicketCreate, TicketUpdate, TicketOut
from app.schemas.tickets import (
    TicketCategorizationRequest,
    TicketCategorizationResponse,
    TicketPriorityRequest,
    TicketPriorityResponse,
)
from app.ai.services.ticket_categorization_service import categorize_ticket_text
from app.ai.services.ticket_priority_service import classify_ticket_priority

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
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["ticket_number"] = _generate_ticket_number(db)
    if data.get("priority"):
        data["priority"] = _normalize_priority(data["priority"])
    obj = Ticket(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[TicketOut])
def list_tickets(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Ticket)
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
    return q.order_by(Ticket.created_at.desc()).all()


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


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    obj = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Ticket not found")
    db.delete(obj)
    db.commit()
    return {"message": "Ticket deleted"}


@router.post("/categorize", response_model=TicketCategorizationResponse)
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
)
def prioritize_ticket_endpoint(payload: TicketPriorityRequest):
    try:
        priority = classify_ticket_priority(payload.text)
        return TicketPriorityResponse(priority=priority)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to classify ticket priority: {exc}") from exc
