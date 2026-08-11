"""Ticket summary endpoints — local ONNX Seq2Seq inference.

    POST /ticket-summaries/generate         summarise arbitrary ticket fields
    GET  /ticket-summaries/by-ticket/{id}   summarise an existing ticket
    GET  /ticket-summaries/health           model readiness
"""
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, is_admin_role
from app.models import Asset, Profile, Ticket
from app.schemas.ticket_summary import TicketSummaryRequest, TicketSummaryResponse
from app.ai.services.ticket_summary_service import (
    build_ticket_summary_input,
    generate_ticket_summary,
    get_ticket_summary_repo,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ticket-summaries", tags=["Ticket Summaries"])


def _s(v) -> str | None:
    return str(v) if v is not None else None


@router.post("/generate", response_model=TicketSummaryResponse)
async def generate_summary(payload: TicketSummaryRequest):
    """Generate a ticket summary from structured fields (or a raw input_text)."""
    try:
        text = payload.input_text or build_ticket_summary_input(
            title=payload.title,
            description=payload.description,
            asset_name=payload.asset_name,
            asset_code=payload.asset_code,
            category=payload.category,
            priority=payload.priority,
        )
        summary = generate_ticket_summary(text)
        return TicketSummaryResponse(summary=summary, generated_at=datetime.utcnow().isoformat())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid input: {e}")
    except Exception as e:  # noqa: BLE001
        logger.error("[TicketSummary] generate failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {e}")


@router.get("/by-ticket/{ticket_id}", response_model=TicketSummaryResponse)
async def get_summary_by_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Fetch a ticket, build its input, and generate a fresh summary.

    Same ownership rule as the rest of the tickets API (see tickets.py):
    admins/super_admins can summarise any ticket, a regular user only one
    they created or are assigned to.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if not is_admin_role(current_user) and str(current_user.id) not in (
        str(ticket.created_by), str(ticket.assigned_to)
    ):
        raise HTTPException(status_code=403, detail="You do not have access to this ticket.")

    asset_name = asset_code = None
    if ticket.asset_id is not None:
        asset = db.query(Asset).filter(Asset.id == ticket.asset_id).first()
        if asset is not None:
            asset_name, asset_code = asset.asset_name, asset.asset_code

    text = build_ticket_summary_input(
        title=ticket.title or "",
        description=ticket.description or "",
        asset_name=asset_name,
        asset_code=asset_code,
        category=_s(ticket.final_category) or _s(ticket.predicted_category),
        priority=_s(ticket.final_priority) or _s(ticket.priority),
    )
    try:
        summary = generate_ticket_summary(text)
        return TicketSummaryResponse(summary=summary, generated_at=datetime.utcnow().isoformat())
    except Exception as e:  # noqa: BLE001
        logger.error("[TicketSummary] by-ticket %s failed: %s", ticket_id, e)
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {e}")


@router.get("/health")
async def health_check():
    """Report which HF Space serves ticket summaries (online inference)."""
    space = get_ticket_summary_repo()
    return {
        "status": "ok" if space else "unconfigured",
        "space": space or None,
        "message": "Ticket summaries served by HF Space" if space
        else "TICKET_SUMMARY_SPACE not set — deterministic fallback in use",
    }
