from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Any
from datetime import datetime


class ReportCreate(BaseModel):
    report_type: str
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    ticket_id: Optional[UUID] = None
    title: str
    generated_by: Optional[UUID] = None
    report_text: Optional[str] = None
    report_json: Optional[Any] = None
    file_path: Optional[str] = None


class ReportUpdate(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    report_text: Optional[str] = None
    report_json: Optional[Any] = None
    file_path: Optional[str] = None
    generation_completed_at: Optional[datetime] = None


class ReportOut(BaseModel):
    id: UUID
    report_type: str
    status: str
    asset_id: Optional[UUID] = None
    warehouse_id: Optional[UUID] = None
    ticket_id: Optional[UUID] = None
    title: str
    generated_by: Optional[UUID] = None

    class Config:
        from_attributes = True