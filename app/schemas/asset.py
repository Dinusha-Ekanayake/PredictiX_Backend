from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import date, datetime


class AssetBase(BaseModel):
    asset_code: str = Field(..., examples=["AST-001"])
    name: str = Field(..., examples=["Conveyor Belt A1"])
    description: Optional[str] = None
    category_id: Optional[int] = None
    location: Optional[str] = None
    asset_family: Optional[str] = None
    status: str = Field(default="ACTIVE")  # ACTIVE / INACTIVE / RETIRED
    criticality: str = Field(default="MEDIUM")  # LOW / MEDIUM / HIGH / CRITICAL
    installation_date: Optional[date] = None
    health_score: Optional[int] = Field(default=None, ge=0, le=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    # allow partial updates
    name: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    location: Optional[str] = None
    asset_family: Optional[str] = None
    status: Optional[str] = None
    criticality: Optional[str] = None
    installation_date: Optional[date] = None
    health_score: Optional[int] = Field(default=None, ge=0, le=100)
    metadata: Optional[Dict[str, Any]] = None


class AssetOut(BaseModel):
    asset_id: int
    asset_code: str
    name: str
    description: Optional[str]
    category_id: Optional[int]
    location: Optional[str]
    asset_family: Optional[str]
    status: str
    criticality: str
    installation_date: Optional[date]
    health_score: Optional[int]
    metadata: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class AssetListOut(BaseModel):
    items: List[AssetOut]
    total: int
    page: int
    page_size: int
