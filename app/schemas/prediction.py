from typing import Any, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime

from pydantic import BaseModel


# =========================
# Existing model inference schemas
# =========================

class PredictionRequest(BaseModel):
    """Raw feature payload for the low-level /predictions/* debug endpoints
    (classification / regression / full). Mirrors the v7 LightGBM models'
    58-feature schema (see predictix_pdm_classifier_v7.txt / _regressor_v7.txt
    feature_names) plus snapshot_date, which run_regression() needs to turn
    a days-until-maintenance prediction into a calendar date.

    Unlike the asset-based /vehicle-predictions/{id} and /batch-predictions/*
    endpoints, this one takes hand-supplied features rather than reading a
    real Asset + SensorReading, intended for testing/debugging the models
    directly. All fields are optional; missing ones are treated as
    0 (numeric) / "" (categorical) by LgbModelBundle.build_frame().
    """
    snapshot_date: Optional[str] = None

    # Categorical (must match the model's trained vocabulary to be used
    # natively; unrecognized values fall back to LightGBM's missing-value
    # handling rather than raising)
    vehicle_type: Optional[str] = None
    vehicle_role: Optional[str] = None
    make_model: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    service_provider_type: Optional[str] = None
    maintenance_priority: Optional[str] = None
    route_type: Optional[str] = None
    cargo_type: Optional[str] = None
    operating_shift: Optional[str] = None
    last_service_type: Optional[str] = None
    parts_replaced_last_service: Optional[str] = None
    major_component_replaced: Optional[str] = None

    # Numeric
    manufacture_year: Optional[int] = None
    vehicle_age_years: Optional[int] = None
    payload_capacity_kg: Optional[float] = None
    odometer_km: Optional[float] = None
    engine_hours_total: Optional[float] = None
    distance_last_30d_km: Optional[float] = None
    operating_hours_last_30d: Optional[float] = None
    idle_hours_last_30d: Optional[float] = None
    trip_count_30d: Optional[int] = None
    avg_trip_distance_km: Optional[float] = None
    avg_payload_kg: Optional[float] = None
    payload_utilization_pct: Optional[float] = None
    overload_events_30d: Optional[int] = None
    start_stop_burden_30d: Optional[int] = None
    rough_road_pct: Optional[float] = None
    urban_route_pct: Optional[float] = None
    port_route_pct: Optional[float] = None
    ambient_temp_avg_c: Optional[float] = None
    ambient_humidity_avg_pct: Optional[float] = None
    rainfall_mm_30d: Optional[float] = None
    fuel_price_lkr_per_l: Optional[float] = None
    engine_temp_avg_c: Optional[float] = None
    coolant_temp_max_c: Optional[float] = None
    vibration_rms_mm_s: Optional[float] = None
    tire_pressure_psi: Optional[float] = None
    fuel_rate_lph: Optional[float] = None
    fuel_efficiency_km_per_l: Optional[float] = None
    battery_voltage_v: Optional[float] = None
    oil_life_pct: Optional[float] = None
    brake_health_pct: Optional[float] = None
    tire_health_pct: Optional[float] = None
    battery_health_pct: Optional[float] = None
    hydraulic_health_pct: Optional[float] = None
    days_since_last_service: Optional[int] = None
    mileage_since_last_service_km: Optional[float] = None
    engine_hours_since_last_service: Optional[float] = None
    maintenance_cost_last_service_lkr: Optional[float] = None
    is_home_warehouse_service: Optional[bool] = None
    active_fault_code_count: Optional[int] = None
    sensor_fault_flag: Optional[bool] = None
    lifetime_service_count: Optional[int] = None
    lifetime_breakdown_count: Optional[int] = None
    downtime_hours_last_90d: Optional[float] = None


# These four response models had drifted away from what the services actually
# return: they declared predicted_class / predicted_label / confidence /
# health_band, none of which prediction_service produces. Because the fields
# were declared required, FastAPI raised ResponseValidationError while
# serialising every successful call, so all four endpoints returned 500 no
# matter what was sent, which is why nothing in the product used them. The
# models below are the real shapes, captured from the services' own output.


class ClassificationResponse(BaseModel):
    maintenance_probability: float
    maintenance_required_next_30d: int
    risk_level: str
    recommended_action: str


class RegressionResponse(BaseModel):
    predicted_days_until_maintenance: int
    predicted_maintenance_date: str
    top_explanations: list[Any] = []


class HealthScoreResponse(BaseModel):
    health_score: float
    #: Canonical band from app/services/health_bands.py (excellent..critical).
    health_status: str
    contributing_factors: list[Any] = []


class FullPredictionResponse(BaseModel):
    maintenance_probability: float
    maintenance_required_next_30d: int
    predicted_days_until_maintenance: int
    predicted_maintenance_date: str
    risk_level: str
    recommended_action: str
    health_score: float
    health_status: str
    top_explanations: list[Any] = []
    contributing_factors: list[Any] = []


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
    """DB-row shape for the legacy asset_cost_predictions table. Only used by
    GET /predictions/cost/run/{run_id} now, GET /predictions/cost/{asset_id}
    and POST /predictions/cost/live/{asset_id} use BreakdownCostPredictionOut
    below instead, since that table is never populated by the breakdown-cost pipeline and
    can't represent SHAP drivers or confidence bounds anyway."""
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


# ── breakdown-cost response shape (v4.0 and v5.0 share this contract) ────────────────────────────────────────
# Mirrors predict_breakdown_cost()'s actual return dict
# (app/ai/models/cost_estimation_model/breakdown_cost_model.py) exactly, this
# is NOT the extra_data-wrapped sample in the older v4 model docs; the code is the
# source of truth, not the doc.

class CostDriverOut(BaseModel):
    feature: str
    value: str
    direction: str          # "increases" | "decreases"
    relative_impact: float  # 0-100, share of total |SHAP|
    # sv_log intentionally omitted, log1p-space value, not meant for display
    # (v4/v5 docs §9: "Never display sv_log directly")


class ExpectedRangeOut(BaseModel):
    p25_lkr: Optional[float] = None
    p75_lkr: Optional[float] = None


class BreakdownCostPredictionOut(BaseModel):
    asset_id: str
    predicted_cost_lkr: float
    pi_80_lower_lkr: float
    pi_80_upper_lkr: float
    coverage_target: str
    fleet_mean_lkr: float
    vs_fleet_mean_lkr: float
    expected_range: ExpectedRangeOut
    sanity_check: str
    top_drivers: list[CostDriverOut]
    model_version: Optional[str] = None
    # Bundle-level accuracy stats (not per-prediction), lets the frontend
    # show the model's real current numbers instead of hardcoding any
    # version's stats, which would go stale the next time the model changes.
    test_r2: Optional[float] = None
    test_mae_lkr: Optional[float] = None
    test_medae_lkr: Optional[float] = None
    picp_80_pct: Optional[float] = None


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