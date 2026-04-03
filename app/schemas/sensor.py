from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from decimal import Decimal

class SensorReadingCreate(BaseModel):
    asset_id: UUID
    temperature: Optional[Decimal] = None
    vibration: Optional[Decimal] = None
    pressure: Optional[Decimal] = None
    humidity: Optional[Decimal] = None
    rpm: Optional[Decimal] = None
    voltage: Optional[Decimal] = None
    fuel_level: Optional[Decimal] = None
    odometer: Optional[Decimal] = None

    engine_hours_since_last_service: Optional[Decimal] = None
    days_since_last_service: Optional[int] = None
    tire_health_pct: Optional[Decimal] = None
    brake_health_pct: Optional[Decimal] = None
    mileage_since_last_service_km: Optional[Decimal] = None
    battery_health_pct: Optional[Decimal] = None
    oil_life_pct: Optional[Decimal] = None
    hydraulic_health_pct: Optional[Decimal] = None
    vibration_rms_mm_s: Optional[Decimal] = None
    fuel_price_lkr_per_l: Optional[Decimal] = None
    engine_hours_total: Optional[Decimal] = None
    coolant_temp_max_c: Optional[Decimal] = None
    engine_temp_avg_c: Optional[Decimal] = None
    battery_voltage_v: Optional[Decimal] = None
    odometer_km: Optional[Decimal] = None
    downtime_hours_last_90d: Optional[Decimal] = None
    active_fault_code_count: Optional[int] = None
    vehicle_age_years: Optional[int] = None
    distance_last_30d_km: Optional[Decimal] = None
    payload_utilization_pct: Optional[Decimal] = None
    trip_count_30d: Optional[int] = None
    ambient_humidity_avg_pct: Optional[Decimal] = None
    rough_road_pct: Optional[Decimal] = None
    idle_hours_last_30d: Optional[Decimal] = None
    port_route_pct: Optional[Decimal] = None
    overload_events_30d: Optional[int] = None
    fuel_rate_lph: Optional[Decimal] = None
    avg_payload_kg: Optional[Decimal] = None