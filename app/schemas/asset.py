from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Any
from decimal import Decimal
from datetime import date


class AssetCreate(BaseModel):
    asset_code: str
    warehouse_id: UUID
    department_id: Optional[UUID] = None
    asset_name: str
    asset_type: str = "vehicle"
    category: Optional[str] = None
    vehicle_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    manufacture_year: Optional[int] = None
    registration_number: Optional[str] = None
    vin: Optional[str] = None
    status: str = "active"
    health_band: Optional[str] = None
    criticality_score: Optional[Decimal] = None
    purchase_date: Optional[date] = None
    warranty_expiry_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    current_mileage: Optional[Decimal] = None
    last_service_date: Optional[date] = None
    next_service_date: Optional[date] = None
    description: Optional[str] = None
    created_by: Optional[UUID] = None
    vehicle_role: Optional[str] = None
    payload_capacity_kg: Optional[Decimal] = None
    vehicle_age_years: Optional[int] = None
    lifetime_service_count: Optional[int] = None
    lifetime_breakdown_count: Optional[int] = None


class AssetUpdate(BaseModel):
    asset_code: Optional[str] = None
    warehouse_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    asset_name: Optional[str] = None
    asset_type: Optional[str] = None
    category: Optional[str] = None
    vehicle_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    manufacture_year: Optional[int] = None
    registration_number: Optional[str] = None
    vin: Optional[str] = None
    status: Optional[str] = None
    health_band: Optional[str] = None
    criticality_score: Optional[Decimal] = None
    purchase_date: Optional[date] = None
    warranty_expiry_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    current_mileage: Optional[Decimal] = None
    last_service_date: Optional[date] = None
    next_service_date: Optional[date] = None
    description: Optional[str] = None
    created_by: Optional[UUID] = None
    vehicle_role: Optional[str] = None
    payload_capacity_kg: Optional[Decimal] = None
    vehicle_age_years: Optional[int] = None
    lifetime_service_count: Optional[int] = None
    lifetime_breakdown_count: Optional[int] = None


class AssetOut(BaseModel):
    id: UUID
    asset_code: str
    warehouse_id: UUID
    department_id: Optional[UUID] = None
    asset_name: str
    asset_type: str
    category: Optional[str] = None
    vehicle_type: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    manufacture_year: Optional[int] = None
    registration_number: Optional[str] = None
    vin: Optional[str] = None
    status: str
    health_band: Optional[str] = None
    criticality_score: Optional[Decimal] = None
    purchase_date: Optional[date] = None
    warranty_expiry_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    current_mileage: Optional[Decimal] = None
    last_service_date: Optional[date] = None
    next_service_date: Optional[date] = None
    description: Optional[str] = None
    created_by: Optional[UUID] = None
    vehicle_role: Optional[str] = None
    payload_capacity_kg: Optional[Decimal] = None
    vehicle_age_years: Optional[int] = None
    lifetime_service_count: Optional[int] = None
    lifetime_breakdown_count: Optional[int] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    make_model: Optional[str] = None
    maintenance_priority: Optional[str] = None
    service_provider_type: Optional[str] = None
    meta: Optional[Any] = None

    class Config:
        from_attributes = True