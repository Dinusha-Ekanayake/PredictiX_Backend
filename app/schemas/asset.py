from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from decimal import Decimal

class AssetCreate(BaseModel):
    asset_code: str
    warehouse_id: UUID
    department_id: Optional[UUID] = None
    asset_name: str
    asset_type: str = "vehicle"
    vehicle_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    manufacture_year: Optional[int] = None
    registration_number: Optional[str] = None
    vin: Optional[str] = None
    status: str = "active"
    assigned_to: Optional[UUID] = None
    current_mileage: Optional[Decimal] = None
    vehicle_role: Optional[str] = None
    payload_capacity_kg: Optional[Decimal] = None

class AssetUpdate(BaseModel):
    asset_name: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[UUID] = None
    current_mileage: Optional[Decimal] = None
    description: Optional[str] = None

class AssetOut(AssetCreate):
    id: UUID

    class Config:
        from_attributes = True