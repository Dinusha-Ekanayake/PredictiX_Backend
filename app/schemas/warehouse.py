from pydantic import BaseModel
from uuid import UUID
from typing import Optional

class WarehouseCreate(BaseModel):
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    country: Optional[str] = "Sri Lanka"

class WarehouseOut(WarehouseCreate):
    id: UUID

    class Config:
        from_attributes = True