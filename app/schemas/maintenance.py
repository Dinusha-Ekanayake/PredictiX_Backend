from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from decimal import Decimal
from datetime import datetime


class MaintenanceEventCreate(BaseModel):
    asset_id: UUID
    event_type: str
    title: str
    description: Optional[str] = None
    performed_by: Optional[UUID] = None
    scheduled_date: Optional[datetime] = None
    performed_at: Optional[datetime] = None
    odometer_reading: Optional[Decimal] = None
    downtime_hours: Optional[Decimal] = None
    cost_amount: Optional[Decimal] = None
    currency: str = "LKR"
    vendor_name: Optional[str] = None
    notes: Optional[str] = None


class MaintenanceEventUpdate(BaseModel):
    event_type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    performed_by: Optional[UUID] = None
    scheduled_date: Optional[datetime] = None
    performed_at: Optional[datetime] = None
    odometer_reading: Optional[Decimal] = None
    downtime_hours: Optional[Decimal] = None
    cost_amount: Optional[Decimal] = None
    currency: Optional[str] = None
    vendor_name: Optional[str] = None
    notes: Optional[str] = None


class MaintenanceEventOut(MaintenanceEventCreate):
    id: UUID

    class Config:
        from_attributes = True