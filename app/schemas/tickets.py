from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


class TicketCreate(BaseModel):
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    title: str
    description: str
    priority: Optional[str] = None
    created_by: UUID


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[UUID] = None
    reviewed_by: Optional[UUID] = None
    final_priority: Optional[str] = None
    final_category: Optional[str] = None
    predicted_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    ticket_summary: Optional[str] = None
    asset_summary: Optional[str] = None


class TicketOut(BaseModel):
    id: UUID
    ticket_number: str
    title: str
    description: str
    status: str
    priority: Optional[str] = None
    predicted_priority: Optional[str] = None
    final_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    final_category: Optional[str] = None
    ticket_summary: Optional[str] = None
    asset_summary: Optional[str] = None
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    created_by: UUID
    assigned_to: Optional[UUID] = None
    reviewed_by: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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


class TicketPriorityRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="Ticket text to classify priority for",
        examples=["Engine overheating alert on Forklift FL-04, coolant leak detected"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "Engine overheating alert on Forklift FL-04, coolant leak detected"
            }
        }
    }


class TicketPriorityResponse(BaseModel):
    priority: str