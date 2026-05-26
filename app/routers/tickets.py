from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Ticket
from app.schemas.tickets import TicketCreate, TicketUpdate, TicketOut

from fastapi import HTTPException
from app.ai.services.ticket_categorization_service import categorize_ticket_text
from app.ai.services.ticket_priority_service import classify_ticket_priority
from app.schemas.tickets import (
    TicketCategorizationRequest,
    TicketCategorizationResponse,
    TicketPriorityRequest,
    TicketPriorityResponse,
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to classify ticket priority: {exc}",
        ) from exc