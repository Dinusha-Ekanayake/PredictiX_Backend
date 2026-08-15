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

class UserSettings(BaseModel):
    """User preference toggles persisted in Profile.meta['settings']."""
    emailNotifications: Optional[bool] = None
    criticalAlerts: Optional[bool] = None
    maintenanceAlerts: Optional[bool] = None
    compactView: Optional[bool] = None

class UserProfileUpdate(BaseModel):
    """Only fields the user is allowed to change"""
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    contactNumber: Optional[str] = None
    address: Optional[str] = None
    settings: Optional[UserSettings] = None

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
    # The asset's real health score (pdm_batch_predictions.health_score), which
    # is what the UI's health bar draws. Nullable on purpose: an asset with no
    # completed prediction has no health to report, and the card renders "—".
    # This was previously fed from criticality_score — a different measure
    # altogether — with a 100.0 default that claimed perfect health for
    # never-scored assets.
    healthPercent: Optional[float] = None
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
    password: Optional[str] = None  # if omitted, the DEFAULT_PASSWORD is hashed

class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    contactNumber: Optional[str] = None

