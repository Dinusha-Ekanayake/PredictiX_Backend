"""
Cost Estimation Service for PredictiX API.

Uses the CatBoost regressor at ai/models/cost_estimation_model/cost_maintenance_model.pkl
to predict the estimated maintenance cost (LKR) for the next 30 days based on
asset details supplied by the user.

The model was trained with 68 features (22 categorical, 46 numeric).
Any feature not supplied by the caller is filled with a safe default so the
model can always produce a prediction.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from catboost import Pool
from fastapi import HTTPException


# ─────────────────────────────────────────────────────────────
# Feature metadata
# ─────────────────────────────────────────────────────────────

ALL_FEATURES: list[str] = [
    "vehicle_id", "snapshot_date", "warehouse_id", "warehouse_name",
    "warehouse_city", "climate_zone", "warehouse_type", "vehicle_type",
    "vehicle_role", "make_model", "fuel_type", "transmission",
    "service_provider_type", "manufacture_year", "vehicle_age_years",
    "payload_capacity_kg", "maintenance_priority", "odometer_km",
    "engine_hours_total", "distance_last_30d_km", "operating_hours_last_30d",
    "idle_hours_last_30d", "trip_count_30d", "avg_trip_distance_km",
    "avg_payload_kg", "payload_utilization_pct", "overload_events_30d",
    "start_stop_burden_30d", "rough_road_pct", "urban_route_pct",
    "port_route_pct", "route_type", "cargo_type", "operating_shift",
    "ambient_temp_avg_c", "ambient_humidity_avg_pct", "rainfall_mm_30d",
    "fuel_price_lkr_per_l", "engine_temp_avg_c", "coolant_temp_max_c",
    "vibration_rms_mm_s", "tire_pressure_psi", "fuel_rate_lph",
    "fuel_efficiency_km_per_l", "battery_voltage_v", "oil_life_pct",
    "brake_health_pct", "tire_health_pct", "battery_health_pct",
    "hydraulic_health_pct", "days_since_last_service",
    "mileage_since_last_service_km", "engine_hours_since_last_service",
    "last_service_type", "parts_replaced_last_service",
    "major_component_replaced", "is_home_warehouse_service",
    "active_fault_code_count", "sensor_fault_flag", "lifetime_service_count",
    "lifetime_breakdown_count", "downtime_hours_last_90d",
    "maintenance_required_next_30d", "next_service_type",
    "spare_parts_delay_days", "maintenance_cost_lkr_next_30d",
    "days_until_next_maintenance", "predicted_next_maintenance_date",
]

# These are the indices the model was trained on as categorical
CATEGORICAL_FEATURE_INDICES: list[int] = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    16, 31, 32, 33, 53, 54, 55, 63, 67,
]

CATEGORICAL_FEATURE_NAMES: list[str] = [
    ALL_FEATURES[i] for i in CATEGORICAL_FEATURE_INDICES
]

# Safe defaults for every feature when the caller does not supply a value
_CAT_DEFAULT = "unknown"
_NUM_DEFAULT = 0.0

_FEATURE_DEFAULTS: dict[str, Any] = {
    # categorical
    "vehicle_id": _CAT_DEFAULT,
    "snapshot_date": "2025-01-01",
    "warehouse_id": _CAT_DEFAULT,
    "warehouse_name": _CAT_DEFAULT,
    "warehouse_city": _CAT_DEFAULT,
    "climate_zone": "tropical",
    "warehouse_type": _CAT_DEFAULT,
    "vehicle_type": _CAT_DEFAULT,
    "vehicle_role": _CAT_DEFAULT,
    "make_model": _CAT_DEFAULT,
    "fuel_type": "diesel",
    "transmission": "manual",
    "service_provider_type": "internal",
    "maintenance_priority": "medium",
    "route_type": "mixed",
    "cargo_type": _CAT_DEFAULT,
    "operating_shift": "day",
    "last_service_type": "routine",
    "parts_replaced_last_service": "none",
    "major_component_replaced": "none",
    "next_service_type": "routine",
    "predicted_next_maintenance_date": _CAT_DEFAULT,
    # numeric
    "manufacture_year": 2020,
    "vehicle_age_years": 3,
    "payload_capacity_kg": 0.0,
    "odometer_km": 0.0,
    "engine_hours_total": 0.0,
    "distance_last_30d_km": 0.0,
    "operating_hours_last_30d": 0.0,
    "idle_hours_last_30d": 0.0,
    "trip_count_30d": 0.0,
    "avg_trip_distance_km": 0.0,
    "avg_payload_kg": 0.0,
    "payload_utilization_pct": 0.0,
    "overload_events_30d": 0.0,
    "start_stop_burden_30d": 0.0,
    "rough_road_pct": 0.0,
    "urban_route_pct": 0.0,
    "port_route_pct": 0.0,
    "ambient_temp_avg_c": 28.0,
    "ambient_humidity_avg_pct": 75.0,
    "rainfall_mm_30d": 0.0,
    "fuel_price_lkr_per_l": 340.0,
    "engine_temp_avg_c": 80.0,
    "coolant_temp_max_c": 90.0,
    "vibration_rms_mm_s": 1.0,
    "tire_pressure_psi": 85.0,
    "fuel_rate_lph": 10.0,
    "fuel_efficiency_km_per_l": 8.0,
    "battery_voltage_v": 12.5,
    "oil_life_pct": 80.0,
    "brake_health_pct": 80.0,
    "tire_health_pct": 80.0,
    "battery_health_pct": 80.0,
    "hydraulic_health_pct": 80.0,
    "days_since_last_service": 0.0,
    "mileage_since_last_service_km": 0.0,
    "engine_hours_since_last_service": 0.0,
    "is_home_warehouse_service": 1,
    "active_fault_code_count": 0.0,
    "sensor_fault_flag": 0,
    "lifetime_service_count": 0.0,
    "lifetime_breakdown_count": 0.0,
    "downtime_hours_last_90d": 0.0,
    "maintenance_required_next_30d": 0,
    "spare_parts_delay_days": 0.0,
    "maintenance_cost_lkr_next_30d": 0.0,   # target column — set 0 for inference
    "days_until_next_maintenance": 30.0,
}


# ─────────────────────────────────────────────────────────────
# Core inference helpers
# ─────────────────────────────────────────────────────────────

def _build_feature_row(user_data: dict[str, Any]) -> dict[str, Any]:
    """
    Merge caller-supplied values with safe defaults to produce a complete
    68-feature row. Categorical features are always strings; numeric features
    are always float.
    """
    row: dict[str, Any] = {}
    for feat in ALL_FEATURES:
        raw = user_data.get(feat, _FEATURE_DEFAULTS.get(feat, _NUM_DEFAULT))
        if feat in CATEGORICAL_FEATURE_NAMES:
            row[feat] = str(raw) if raw is not None else _CAT_DEFAULT
        else:
            try:
                row[feat] = float(raw) if raw is not None else _NUM_DEFAULT
            except (TypeError, ValueError):
                row[feat] = _NUM_DEFAULT
    return row


def _make_pool(row: dict[str, Any]) -> Pool:
    df = pd.DataFrame([row])[ALL_FEATURES]
    return Pool(
        data=df,
        cat_features=CATEGORICAL_FEATURE_INDICES,
    )


# ─────────────────────────────────────────────────────────────
# SHAP Explanations
# ─────────────────────────────────────────────────────────────

def _get_top_cost_shap(cost_model, pool: Pool) -> list[dict]:
    """
    Calculate SHAP values for the prediction to explain which features
    had the most impact (positive or negative) on the estimated cost.
    """
    try:
        # get_feature_importance with type='ShapValues' returns an array where
        # each row has [shap_feat1, shap_feat2, ..., base_value]
        shap_values = cost_model.get_feature_importance(type="ShapValues", data=pool)
        
        # We only have one row in our pool
        row_shap = shap_values[0][:-1]
        
        ranked = sorted(
            zip(ALL_FEATURES, row_shap),
            key=lambda x: abs(x[1]),
            reverse=True,
        )
        
        return [
            {
                "feature": feature,
                "impact_value": round(float(impact), 2),
                "direction": "Increase" if impact > 0 else "Decrease",
                "display_impact": abs(round(float(impact), 2))
            }
            for feature, impact in ranked[:8]   # Return top 8 factors
            if abs(impact) > 0.01              # Only include meaningful impacts
        ]
    except Exception as e:
        print(f"WARNING: SHAP calculation failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────

def run_cost_estimation(user_data: dict[str, Any], cost_model) -> dict[str, Any]:
    """
    Run the cost_maintenance_model on the supplied asset details.

    Returns estimated_cost, min_cost, max_cost and the full feature row
    used for inference.

    Raises HTTPException(500) on model errors.
    """
    if cost_model is None:
        raise HTTPException(
            status_code=500,
            detail="Cost estimation model is not loaded.",
        )

    try:
        row = _build_feature_row(user_data)
        pool = _make_pool(row)

        raw_prediction = float(cost_model.predict(pool)[0])
        # Clamp to a sensible positive range (LKR)
        estimated_cost = max(1_000.0, round(raw_prediction, 2))

        # Derive min / max bands (±15 % / ±25 %)
        min_cost = round(estimated_cost * 0.85, 2)
        avg_cost = round(estimated_cost, 2)
        max_cost = round(estimated_cost * 1.25, 2)

        # Get SHAP explanations
        top_explanations = _get_top_cost_shap(cost_model, pool)

        return {
            "estimated_cost_lkr": avg_cost,
            "min_cost_lkr": min_cost,
            "max_cost_lkr": max_cost,
            "currency": "LKR",
            "top_explanations": top_explanations,
            "features_used": {
                k: v for k, v in row.items()
                if k not in ("maintenance_cost_lkr_next_30d",)   # exclude leakage col
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Cost estimation failed: {exc}",
        ) from exc
