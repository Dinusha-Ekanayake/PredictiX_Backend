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
    warehouse: Optional[str] = None
    contact_number: Optional[str] = None

class UserOut(BaseModel):
    user_id: UUID
    user_name: str
    email: EmailStr
    role: str
    is_active: bool

class UserBase(BaseModel):
    username: str
    email: str
class UserUpdate(BaseModel):
    username: str
    email: str

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int

    class Config:
        orm_mode = True