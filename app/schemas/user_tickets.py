"""Pydantic schemas for the user-role ticket endpoints (`/user/tickets`).

These mirror the shapes consumed by the admin tickets section but are scoped
to fields a regular user is allowed to see or change. Anything admin-only
(status transitions, assignee, reviewer, final_*) is intentionally absent
from the input schemas so it cannot be set via these routes.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inputs (what the user is allowed to send)
# ---------------------------------------------------------------------------


class UserTicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    priority: Optional[str] = Field(
        default=None,
        description="Optional user-supplied priority. AI may override or fill if empty.",
    )
    use_ai_predictions: bool = Field(
        default=True,
        description="Run priority + summary models on create. Soft-fails if HF is down.",
    )
    # When the user has already previewed the AI suggestions in the dialog and
    # accepted them, the frontend re-sends those values here and sets
    # `use_ai_predictions=False` so the backend stores them without re-running
    # the models. Ignored when `use_ai_predictions=True`.
    predicted_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    ticket_summary: Optional[str] = None


class UserTicketPreviewRequest(BaseModel):
    """Body for POST /user/tickets/preview, same shape as create, minus DB ids."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    asset_id: Optional[UUID] = None
    priority: Optional[str] = None


class UserTicketPreviewResponse(BaseModel):
    """AI predictions returned by the preview endpoint. Any field may be null
    if its model is unavailable."""

    predicted_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    ticket_summary: Optional[str] = None
    # Surface why a field is missing (e.g. HF model not deployed) so the UI
    # can show a meaningful note instead of an empty cell.
    errors: dict[str, str] = Field(default_factory=dict)


class UserTicketUpdate(BaseModel):
    """Users may only edit title / description / priority of their own tickets."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, min_length=1)
    priority: Optional[str] = None


class UserTicketCommentCreate(BaseModel):
    comment: str = Field(..., min_length=1)


class UserTicketAttachmentCreate(BaseModel):
    file_path: str
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class UserTicketSummary(BaseModel):
    """Compact row used in list responses."""

    id: UUID
    ticket_number: str
    title: str
    status: str
    priority: Optional[str] = None
    predicted_priority: Optional[str] = None
    final_priority: Optional[str] = None
    predicted_category: Optional[str] = None
    final_category: Optional[str] = None
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserTicketCommentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    user_id: UUID
    comment: str
    is_internal: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class UserTicketAttachmentOut(BaseModel):
    id: UUID
    ticket_id: UUID
    file_path: str
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
    uploaded_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserTicketHistoryOut(BaseModel):
    id: UUID
    ticket_id: UUID
    old_status: Optional[str] = None
    new_status: str
    changed_by: Optional[UUID] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserTicketDetail(UserTicketSummary):
    """Full ticket view including description, AI fields, and related rows."""

    description: str
    ticket_summary: Optional[str] = None
    asset_summary: Optional[str] = None
    created_by: UUID
    assigned_to: Optional[UUID] = None
    reviewed_by: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    comments: list[UserTicketCommentOut] = []
    attachments: list[UserTicketAttachmentOut] = []
    history: list[UserTicketHistoryOut] = []


class UserTicketListResponse(BaseModel):
    items: list[UserTicketSummary]
    total: int
    page: int
    page_size: int
