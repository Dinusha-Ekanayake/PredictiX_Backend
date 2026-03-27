from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from typing import List
from decimal import Decimal
from datetime import date, datetime

class PredictionRequest(BaseModel):
    snapshot_date: str = Field(..., example="2025-03-01")

    model_config = ConfigDict(extra="allow")


class FeatureExplanation(BaseModel):
    feature: str
    impact: float


class ClassificationResponse(BaseModel):
    maintenance_probability: float
    maintenance_required_next_30d: int
    risk_level: str
    recommended_action: str


class RegressionResponse(BaseModel):
    predicted_days_until_maintenance: int
    predicted_maintenance_date: str
    top_explanations: List[FeatureExplanation]


class HealthScoreResponse(BaseModel):
    health_score: float
    health_status: str
    contributing_factors: List[FeatureExplanation]


class FullPredictionResponse(BaseModel):
    maintenance_probability: float
    maintenance_required_next_30d: int
    predicted_days_until_maintenance: int
    predicted_maintenance_date: str
    risk_level: str
    recommended_action: str
    health_score: float
    health_status: str
    top_explanations: List[FeatureExplanation]
    contributing_factors: List[FeatureExplanation]


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool


class DebugFeaturesResponse(BaseModel):
    classifier_features: list[str]
    regressor_features: list[str]
    regressor_categorical_features: list[str]

class PredictionRunOut(BaseModel):
    id: UUID
    model_id: UUID
    asset_id: Optional[UUID] = None
    ticket_id: Optional[UUID] = None
    requested_by: Optional[UUID] = None
    run_started_at: Optional[datetime] = None
    run_finished_at: Optional[datetime] = None
    status: str
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class AssetFailurePredictionOut(BaseModel):
    id: UUID
    run_id: UUID
    asset_id: UUID
    health_score: Optional[Decimal] = None
    failure_probability: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    risk_level: Optional[str] = None
    predicted_maintenance_date: Optional[date] = None
    days_until_maintenance: Optional[int] = None
    top_explanations: Optional[Any] = None

    class Config:
        from_attributes = True


class AssetCostPredictionOut(BaseModel):
    id: UUID
    run_id: UUID
    asset_id: UUID
    estimated_cost: Optional[Decimal] = None
    min_cost: Optional[Decimal] = None
    max_cost: Optional[Decimal] = None
    currency: Optional[str] = None
    confidence_score: Optional[Decimal] = None

    class Config:
        from_attributes = True


class TicketPredictionOut(BaseModel):
    id: UUID
    run_id: UUID
    ticket_id: UUID
    predicted_category: Optional[str] = None
    predicted_priority: Optional[str] = None
    category_confidence: Optional[Decimal] = None
    priority_confidence: Optional[Decimal] = None
    generated_summary: Optional[str] = None

    class Config:
        from_attributes = True