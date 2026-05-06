from pydantic import BaseModel
from typing import Optional

class UserProfileOut(BaseModel):
    """Full profile shown on /user/users page"""
    id: str
    employee_id: Optional[str]
    firstName: str              # split from full_name
    lastName: str
    name: str                   # full_name
    email: str
    contactNumber: Optional[str]  # phone field
    address: Optional[str]        # from meta JSONB
    department: Optional[str]     # department NAME (joined)
    department_id: Optional[str]
    warehouse: Optional[str]      # warehouse NAME (joined)
    warehouse_id: Optional[str]
    role: str
    status: str
    assignedAssetsCount: int      # COUNT of active assignments

class UserProfileUpdate(BaseModel):
    """Only fields the user is allowed to change"""
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    contactNumber: Optional[str] = None
    address: Optional[str] = None

class UserAssignedAssetOut(BaseModel):
    """One asset card on the profile page"""
    assignment_id: str
    asset_id: str
    asset_code: str
    name: str            # asset_name
    asset_type: str
    category: Optional[str]
    location: str        # warehouse name + city
    status: str          # asset status
    healthPercent: float # from criticality_score or health_score
    nextServiceDate: Optional[str]

class UserItemOut(BaseModel):
    id: str
    firstName: str
    lastName: str
    name: str
    email: str
    address: str
    contactNumber: str
    warehouse: str
    role: str
    department: str
    status: str
    assignedAssets: int

class UserCreate(BaseModel):
    id: str  # E.g. "U0005E" coming from the frontend generator
    firstName: str
    lastName: str
    name: str
    email: str
    address: str
    contactNumber: str
    warehouse: str
    role: str
    department: str
    status: str

class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    contactNumber: Optional[str] = None

class TeamMemberOut(BaseModel):
    """Team member shown in department section"""
    id: str
    employee_id: Optional[str]
    firstName: str
    lastName: str
    name: str
    email: str
    contactNumber: Optional[str]
    department: Optional[str]
    role: str
    status: str
    warehouse: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = None
