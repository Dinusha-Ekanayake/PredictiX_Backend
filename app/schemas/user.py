from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import date


class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: Optional[str] = None
    role: Optional[str] = "USER"
    status: Optional[str] = "active"
    department: Optional[str] = None
    residence_address: Optional[str] = None
    contact_no: Optional[str] = None
    warehouse: Optional[str] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    residence_address: Optional[str] = None
    contact_no: Optional[str] = None
    warehouse: Optional[str] = None


class UserOut(BaseModel):
    user_id: UUID
    first_name: str
    last_name: str
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    residence_address: Optional[str] = None
    contact_no: Optional[str] = None
    warehouse: Optional[str] = None
    created_at: Optional[date] = None

    model_config = {"from_attributes": True}