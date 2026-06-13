from pydantic import BaseModel, EmailStr
from uuid import UUID
from typing import Optional


class ProfileUpdate(BaseModel):
    employee_id: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    warehouse_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    avatar_url: Optional[str] = None


class ProfileOut(BaseModel):
    id: UUID
    employee_id: Optional[str] = None
    full_name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: str
    status: str
    warehouse_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True