from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional
from decimal import Decimal
from datetime import date, datetime


class MaintenanceLogRequest(BaseModel):
    """Body for ``POST /maintenance/log-maintenance/{asset_id}``.

    Deliberately narrower than :class:`MaintenanceEventCreate`. That schema is
    the generic "insert a row" shape and needs ``asset_id`` and ``event_type``
    supplied by the caller; this one is the operator-facing action of recording
    a completed service against one asset, so the asset comes from the path,
    ``event_type`` has a sensible default, and ``performed_by`` is taken from
    the authenticated user rather than trusted from the client.

    ``next_service_date`` has no column on ``maintenance_events``, it belongs
    to the asset. Logging a service is what advances it, which is precisely the
    behaviour the generic insert endpoint cannot express.
    """

    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    cost_amount: Optional[Decimal] = Field(default=None, ge=0)
    odometer_reading: Optional[Decimal] = Field(default=None, ge=0)
    downtime_hours: Optional[Decimal] = Field(default=None, ge=0)
    next_service_date: Optional[date] = None
    performed_at: Optional[datetime] = None
    vendor_name: Optional[str] = None
    notes: Optional[str] = None
    # Free text rather than an enum here: maintenance_event_type is a Postgres
    # enum, and the router validates against it so an unknown value is a clean
    # 422 instead of a 500 from the driver.
    event_type: str = "scheduled_service"


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