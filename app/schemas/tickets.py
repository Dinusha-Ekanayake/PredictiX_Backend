from pydantic import BaseModel
from uuid import UUID
from typing import Optional

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