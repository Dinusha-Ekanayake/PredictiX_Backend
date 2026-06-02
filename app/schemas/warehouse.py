from pydantic import BaseModel
from uuid import UUID
from typing import Optional, Any

class WarehouseCreate(BaseModel):
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    country: Optional[str] = "Sri Lanka"

class WarehouseOut(WarehouseCreate):
    id: UUID
    climate_zone: Optional[str] = None
    warehouse_type: Optional[str] = None
    meta: Optional[Any] = None

    class Config:
        from_attributes = True