from typing import Any, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime

from pydantic import BaseModel


# =========================
# Existing model inference schemas
# =========================

class PredictionRequest(BaseModel):
    engine_hours_since_last_service: Optional[float] = None
    days_since_last_service: Optional[int] = None
    tire_health_pct: Optional[float] = None
    brake_health_pct: Optional[float] = None
    mileage_since_last_service_km: Optional[float] = None
    battery_health_pct: Optional[float] = None
    oil_life_pct: Optional[float] = None
    hydraulic_health_pct: Optional[float] = None
    vibration_rms_mm_s: Optional[float] = None
    fuel_price_lkr_per_l: Optional[float] = None
    engine_hours_total: Optional[float] = None
    coolant_temp_max_c: Optional[float] = None
    lifetime_service_count: Optional[int] = None
    engine_temp_avg_c: Optional[float] = None
    battery_voltage_v: Optional[float] = None
    odometer_km: Optional[float] = None
    downtime_hours_last_90d: Optional[float] = None
    active_fault_code_count: Optional[int] = None
    vehicle_age_years: Optional[int] = None
    distance_last_30d_km: Optional[float] = None
    payload_utilization_pct: Optional[float] = None
    trip_count_30d: Optional[int] = None
    ambient_humidity_avg_pct: Optional[float] = None
    rough_road_pct: Optional[float] = None
    idle_hours_last_30d: Optional[float] = None
    vehicle_role: Optional[str] = None
    port_route_pct: Optional[float] = None
    overload_events_30d: Optional[int] = None
    fuel_rate_lph: Optional[float] = None
    payload_capacity_kg: Optional[float] = None
    avg_payload_kg: Optional[float] = None
    lifetime_breakdown_count: Optional[int] = None


class ClassificationResponse(BaseModel):
    predicted_class: int
    predicted_label: str
    confidence: float


class RegressionResponse(BaseModel):
    predicted_days_until_maintenance: float


class HealthScoreResponse(BaseModel):
    health_score: float
    health_band: str


class FullPredictionResponse(BaseModel):
    predicted_class: int
    predicted_label: str
    confidence: float
    predicted_days_until_maintenance: float
    health_score: float
    health_band: str


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool


class DebugFeaturesResponse(BaseModel):
    classifier_features: list[str]
    regressor_features: list[str]
    regressor_categorical_features: list[str]


# =========================
# Database prediction schemas
# =========================

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

class VehiclePredictionStoredResponse(BaseModel):
    run_id: str
    asset_id: str
    predicted_class: int
    predicted_label: str
    failure_probability: float
    confidence: float
    predicted_days_until_maintenance: float
    predicted_maintenance_date: str
    health_score: float
    health_band: str
    risk_level: str
    estimated_cost_lkr: float
    min_cost_lkr: float
    max_cost_lkr: float
    features_used: dict[str, Any]