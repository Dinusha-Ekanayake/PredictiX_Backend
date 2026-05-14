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


# =========================
# Cost Estimation schemas
# =========================

class CostEstimationRequest(BaseModel):
    """
    Asset details submitted by the user when adding / viewing an asset.
    All fields are optional — the model applies safe defaults for any missing value.

    Core asset fields (from AssetCreate) are listed first;
    operational / sensor fields follow for more accurate estimates.
    """
    # ── Core asset identity ──────────────────────────────────
    vehicle_id: Optional[str] = None           # asset_code or asset id (string)
    snapshot_date: Optional[str] = None        # YYYY-MM-DD; defaults to today
    warehouse_id: Optional[str] = None
    warehouse_name: Optional[str] = None
    warehouse_city: Optional[str] = None
    warehouse_type: Optional[str] = None
    climate_zone: Optional[str] = None

    # ── Vehicle / asset specs ────────────────────────────────
    vehicle_type: Optional[str] = None
    vehicle_role: Optional[str] = None
    make_model: Optional[str] = None           # "{make} {model}" combined string
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    manufacture_year: Optional[int] = None
    vehicle_age_years: Optional[int] = None
    payload_capacity_kg: Optional[float] = None

    # ── Maintenance context ───────────────────────────────────
    maintenance_priority: Optional[str] = None
    service_provider_type: Optional[str] = None
    last_service_type: Optional[str] = None
    parts_replaced_last_service: Optional[str] = None
    major_component_replaced: Optional[str] = None
    is_home_warehouse_service: Optional[int] = None
    next_service_type: Optional[str] = None
    spare_parts_delay_days: Optional[float] = None
    maintenance_required_next_30d: Optional[int] = None
    days_until_next_maintenance: Optional[float] = None
    predicted_next_maintenance_date: Optional[str] = None

    # ── Odometer / usage ─────────────────────────────────────
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
    start_stop_burden_30d: Optional[float] = None

    # ── Route / environment ───────────────────────────────────
    rough_road_pct: Optional[float] = None
    urban_route_pct: Optional[float] = None
    port_route_pct: Optional[float] = None
    route_type: Optional[str] = None
    cargo_type: Optional[str] = None
    operating_shift: Optional[str] = None
    ambient_temp_avg_c: Optional[float] = None
    ambient_humidity_avg_pct: Optional[float] = None
    rainfall_mm_30d: Optional[float] = None
    fuel_price_lkr_per_l: Optional[float] = None

    # ── Sensor / health readings ──────────────────────────────
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

    # ── Service history ───────────────────────────────────────
    days_since_last_service: Optional[float] = None
    mileage_since_last_service_km: Optional[float] = None
    engine_hours_since_last_service: Optional[float] = None
    lifetime_service_count: Optional[int] = None
    lifetime_breakdown_count: Optional[int] = None

    # ── Fault / downtime ──────────────────────────────────────
    active_fault_code_count: Optional[int] = None
    sensor_fault_flag: Optional[int] = None
    downtime_hours_last_90d: Optional[float] = None


class CostEstimationResponse(BaseModel):
    """Estimated maintenance cost for the next 30 days, in LKR."""
    estimated_cost_lkr: float
    min_cost_lkr: float
    max_cost_lkr: float
    currency: str
    top_explanations: list[dict[str, Any]]
    features_used: dict[str, Any]