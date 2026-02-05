from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID

class UserCreate(BaseModel):
    user_name: str
    email: EmailStr
    contact_no: Optional[str] = None
    password: str
    role: str = "USER"
    dept_id: Optional[int] = None

class UserOut(BaseModel):
    user_id: UUID
    user_name: str
    email: EmailStr
    role: str
    is_active: bool

    class Config:
        from_attributes = True
