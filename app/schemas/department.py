from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class DepartmentCreate(BaseModel):
    warehouse_id: Optional[UUID] = None
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool = True


class DepartmentUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentOut(DepartmentCreate):
    id: UUID

    class Config:
        from_attributes = True