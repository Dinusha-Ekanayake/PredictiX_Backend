from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


# ── User (owner-scoped) ticket schemas ────────────────────────────────────────
# Used by the /tickets/mine* endpoints, which authenticate via the app JWT and
# enforce that a non-admin user may only see/modify tickets they created.

class UserTicketCreate(BaseModel):
    asset_id: Optional[UUID] = None
    title: str
    description: str = ""
    priority: Optional[str] = "medium"      # high | medium | low
    category: Optional[str] = "mechanical"  # -> predicted_category


class UserTicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None          # -> predicted_category


class UserTicketOut(BaseModel):
    id: UUID
    ticket_number: Optional[str] = None
    asset_id: Optional[UUID] = None
    asset_name: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    priority: Optional[str] = None
    predicted_category: Optional[str] = None
    final_category: Optional[str] = None
    created_by: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class TicketCreate(BaseModel):
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    title: str
    description: str
    created_by: UUID


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[UUID] = None
    reviewed_by: Optional[UUID] = None
    final_priority: Optional[str] = None
    final_category: Optional[str] = None
    ticket_summary: Optional[str] = None
    asset_summary: Optional[str] = None


class TicketOut(BaseModel):
    id: UUID
    ticket_number: str
    title: str
    description: str
    status: str

    class Config:
        from_attributes = True

from pydantic import BaseModel, Field


class TicketCategorizationRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class TicketCategoryScore(BaseModel):
    label: str
    score: float


class TicketCategorizationResponse(BaseModel):
    predicted_label: str
    confidence: float
    scores: list[TicketCategoryScore]