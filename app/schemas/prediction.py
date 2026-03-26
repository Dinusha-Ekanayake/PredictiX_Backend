from pydantic import BaseModel, ConfigDict, Field
from typing import List


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