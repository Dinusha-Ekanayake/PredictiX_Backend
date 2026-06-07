from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


class NotificationCreate(BaseModel):
    user_id: UUID
    type: str
    channel: str = "in_app"
    title: str
    message: str
    status: str = "unread"
    related_asset_id: Optional[UUID] = None
    related_ticket_id: Optional[UUID] = None
    related_report_id: Optional[UUID] = None


class NotificationUpdate(BaseModel):
    status: Optional[str] = None
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None


class NotificationOut(BaseModel):
    id: UUID
    user_id: UUID
    type: str
    channel: str
    title: str
    message: str
    status: str
    meta: Optional[dict] = {}
    created_at: datetime

    class Config:
        from_attributes = True