from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from datetime import datetime


class NotificationCreate(BaseModel):
    user_id: Optional[UUID] = None
    type: Optional[str] = "system"
    channel: str = "in_app"
    title: str
    message: str
    status: str = "unread"
    related_asset_id: Optional[UUID] = None
    related_ticket_id: Optional[UUID] = None
    related_report_id: Optional[UUID] = None
    link_url: Optional[str] = None
    priority: Optional[str] = "low"
    meta: Optional[dict] = None


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
    created_at: Optional[datetime] = None
    meta: Optional[dict] = None

    class Config:
        from_attributes = True