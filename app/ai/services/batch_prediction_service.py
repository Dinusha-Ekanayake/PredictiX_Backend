"""Batch PDM prediction service.

Runs the full PDM pipeline (classification, regression, health score, cost
estimation) for **every active asset** and upserts one row per asset into the
``pdm_batch_predictions`` table.

Designed to be invoked:
 - By the APScheduler inside FastAPI every N hours (started in ``main.py``).
 - Via the ``POST /batch-predictions/run`` REST endpoint for manual triggers.
 - Via the ``POST /batch-predictions/run/{asset_id}`` endpoint for a single asset.

Performance note
----------------
The whole-fleet run fetches every asset's latest sensor reading in a single
set-based query (``DISTINCT ON``), runs both models once on a batched
DataFrame (classifier + regressor + SHAP all support multi-row input), and
upserts every result in one multi-row ``INSERT ... ON CONFLICT`` statement
with a single commit — instead of one query + one insert + one commit per
asset. For ~1000 assets this turns ~3000 DB round-trips/run into ~3.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import String, cast, text
from sqlalchemy.orm import Session

from app.models import Asset, PdmBatchPrediction
from app.ai.services.pdm_decision_service import build_decision

# v7 regressor was trained on days_until_next_maintenance up to 365 (see
# regressor_v7_decision_log.json) — the old 180-day clamp was arbitrary and
# not something this model generation was trained to respect. Predictions at
# or past this ceiling are flagged via horizon_saturated instead of being
# rendered as a literal (and misleadingly precise) date.
REGRESSOR_HORIZON_DAYS = 365

log = logging.getLogger("predictix.batch")


def _model_version_tag() -> str:
    """``"classifier=<version>,regressor=<version>"`` read from main's loaded
    decision-log metadata, for the model_version audit column. Falls back to
    "unknown" for either side if main.py's models aren't loaded/registered
    yet (e.g. this service imported outside the app's normal boot path)."""
    try:
        from app.main import CLF_DECISION_LOG_PATH, REG_DECISION_LOG_PATH, _load_decision_log
        clf_version = _load_decision_log(CLF_DECISION_LOG_PATH).get("version", "unknown")
        reg_version = _load_decision_log(REG_DECISION_LOG_PATH).get("version", "unknown")
        return f"classifier={clf_version},regressor={reg_version}"
    except Exception:
        return "unknown"


def _empty_prediction_fields() -> dict[str, Any]:
    """All ``_UPSERT_COLUMNS`` set to their "nothing computed" default —
    shared by the no-sensor-data and error branches so both stay in sync
    with the column list as it grows."""
    return {
        "failure_probability": None,
        "maintenance_required": None,
        "risk_level": None,
        "predicted_days_until_maintenance": None,
        "predicted_maintenance_date": None,
        "health_score": None,
        "health_status": None,
        "contributing_factors": "[]",
        "estimated_cost_lkr": None,
        "min_cost_lkr": None,
        "max_cost_lkr": None,
        "top_explanations": "[]",
        "model_version": None,
        "feature_snapshot": "{}",
        "tier": None,
        "agreement": None,
        "display_mode": None,
        "horizon_text": None,
        "recommended_action": None,
        "horizon_saturated": False,
    }

# ── sklearn compatibility shim ──────────────────────────────────────────────
# The regressor bundle was pickled with an older sklearn that had _RemainderColsList.
# Newer sklearn (>=1.4) removed it; we inject it back so joblib.load() succeeds.
try:
    import sklearn.compose._column_transformer as _sct
    if not hasattr(_sct, "_RemainderColsList"):
        class _RemainderColsList(list):  # type: ignore[no-redef]
            pass
        _sct._RemainderColsList = _RemainderColsList  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Small scalar helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────────────────────
# Feature dict (same shape as before — one dict per asset)
# ──────────────────────────────────────────────────────────────────────────────

_SENSOR_FLOAT_COLS = [
    "engine_hours_since_last_service",
    "tire_health_pct",
    "brake_health_pct",
    "mileage_since_last_service_km",
    "battery_health_pct",
    "oil_life_pct",
    "hydraulic_health_pct",
    "vibration_rms_mm_s",
    "fuel_price_lkr_per_l",
    "engine_hours_total",
    "coolant_temp_max_c",
    "engine_temp_avg_c",
    "battery_voltage_v",
    "odometer_km",
    "downtime_hours_last_90d",
    "distance_last_30d_km",
    "payload_utilization_pct",
    "ambient_humidity_avg_pct",
    "rough_road_pct",
    "idle_hours_last_30d",
    "port_route_pct",
    "fuel_rate_lph",
    "avg_payload_kg",
    "ambient_temp_avg_c",
    "avg_trip_distance_km",
    "fuel_efficiency_km_per_l",
    "maintenance_cost_last_service_lkr",
    "rainfall_mm_30d",
    "tire_pressure_psi",
    "operating_hours_last_30d",
    "urban_route_pct",
]
_SENSOR_INT_COLS = [
    "days_since_last_service",
    "active_fault_code_count",
    "trip_count_30d",
    "overload_events_30d",
    "start_stop_burden_30d",
]
_SENSOR_BOOL_COLS = [
    "sensor_fault_flag",
    "is_home_warehouse_service",
]
_SENSOR_STR_COLS = [
    "route_type",
    "cargo_type",
    "operating_shift",
    "last_service_type",
    "parts_replaced_last_service",
    "major_component_replaced",
]


def _build_feature_dict(asset: Asset, reading, snapshot_date: date | None = None) -> dict[str, Any]:
    """Build the feature dict from an Asset ORM row + its latest SensorReading.

    ``snapshot_date`` seeds the ``month``/``year`` engineered features the v7
    models were trained on (see predictix_pm_model_v7_*.ipynb: ``df['month']
    = df.snapshot_date.dt.month; df['year'] = df.snapshot_date.dt.year``).
    Defaults to today when not given (i.e. every live batch/single-asset run).
    """
    fd: dict[str, Any] = {}

    snapshot_date = snapshot_date or date.today()
    fd["month"] = snapshot_date.month
    fd["year"] = snapshot_date.year

    # Asset-level features
    fd["vehicle_role"] = str(asset.vehicle_role or asset.vehicle_type or "transport")
    fd["vehicle_type"] = str(asset.vehicle_type or "")
    fd["make_model"] = str(asset.make_model or "")
    fd["fuel_type"] = str(asset.fuel_type or "")
    fd["transmission"] = str(asset.transmission or "")
    fd["maintenance_priority"] = str(asset.maintenance_priority or "")
    fd["service_provider_type"] = str(asset.service_provider_type or "")
    fd["payload_capacity_kg"] = _to_float(asset.payload_capacity_kg)
    fd["vehicle_age_years"] = _to_int(asset.vehicle_age_years)
    fd["manufacture_year"] = _to_int(asset.manufacture_year)
    fd["lifetime_service_count"] = _to_int(asset.lifetime_service_count)
    fd["lifetime_breakdown_count"] = _to_int(asset.lifetime_breakdown_count)

    for col in _SENSOR_FLOAT_COLS:
        fd[col] = _to_float(getattr(reading, col, None))
    for col in _SENSOR_INT_COLS:
        fd[col] = _to_int(getattr(reading, col, None))
    for col in _SENSOR_BOOL_COLS:
        val = getattr(reading, col, None)
        fd[col] = bool(val) if val is not None else False
    for col in _SENSOR_STR_COLS:
        fd[col] = str(getattr(reading, col, None) or "")

    return fd


# ──────────────────────────────────────────────────────────────────────────────
# Breakdown cost model input builder
# Converts the feature dict (PDM-shape) into the cost model's expected input.
# ──────────────────────────────────────────────────────────────────────────────

def _build_cost_input_from_fd(asset: Asset, fd: dict[str, Any]) -> dict[str, Any]:
    """Build raw_input dict for predict_breakdown_cost() from an asset ORM
    object and the already-built PDM feature dict.

    Uses the feature dict (which already has sensor fields resolved) rather
    than hitting the DB again for a MaintenanceEvent.
    """
    return {
        # Identity
        "vehicle_type"                    : str(asset.vehicle_type or ""),
        "vehicle_role"                    : str(asset.vehicle_role or "__missing__"),
        "make_model"                      : str(asset.make_model or "__missing__"),
        "fuel_type"                       : str(asset.fuel_type or "__missing__"),
        "transmission"                    : str(asset.transmission or "__missing__"),
        "manufacture_year"                : _to_int(asset.manufacture_year, 2015),
        # Usage
        "vehicle_age_years"               : _to_float(asset.vehicle_age_years),
        "payload_capacity_kg"             : _to_float(asset.payload_capacity_kg),
        "odometer_km"                     : _to_float(fd.get("odometer_km", 0)),
        "engine_hours_total"              : _to_float(fd.get("engine_hours_total", 0)),
        "lifetime_service_count"          : _to_int(asset.lifetime_service_count),
        "lifetime_breakdown_count"        : _to_int(asset.lifetime_breakdown_count),
        # Health signals (from sensor reading via fd)
        "oil_life_pct"                    : _to_float(fd.get("oil_life_pct", 50)),
        "brake_health_pct"                : _to_float(fd.get("brake_health_pct", 50)),
        "tire_health_pct"                 : _to_float(fd.get("tire_health_pct", 50)),
        "battery_health_pct"              : _to_float(fd.get("battery_health_pct", 50)),
        "hydraulic_health_pct"            : _to_float(fd.get("hydraulic_health_pct", 50)),
        "active_fault_code_count"         : _to_int(fd.get("active_fault_code_count", 0)),
        "sensor_fault_flag"               : int(bool(fd.get("sensor_fault_flag", False))),
        # Operational
        "fuel_price_lkr_per_l"            : _to_float(fd.get("fuel_price_lkr_per_l", 310.0)),
        "downtime_hours_last_90d"         : _to_float(fd.get("downtime_hours_last_90d", 0)),
        "payload_utilization_pct"         : _to_float(fd.get("payload_utilization_pct", 50)),
        "engine_hours_since_last_service" : _to_float(fd.get("engine_hours_since_last_service", 0)),
        "days_since_last_service"         : _to_int(fd.get("days_since_last_service", 0)),
        "mileage_since_last_service_km"   : _to_float(fd.get("mileage_since_last_service_km", 0)),
        "avg_payload_kg"                  : _to_float(fd.get("avg_payload_kg", 0)),
        "overload_events_30d"             : _to_int(fd.get("overload_events_30d", 0)),
        "distance_last_30d_km"            : _to_float(fd.get("distance_last_30d_km", 0)),
        "operating_hours_last_30d"        : _to_float(fd.get("operating_hours_last_30d", 0)),
        "idle_hours_last_30d"             : _to_float(fd.get("idle_hours_last_30d", 0)),
        "trip_count_30d"                  : _to_int(fd.get("trip_count_30d", 0)),
        "avg_trip_distance_km"            : _to_float(fd.get("avg_trip_distance_km", 0)),
        "start_stop_burden_30d"           : _to_int(fd.get("start_stop_burden_30d", 0)),
        "rough_road_pct"                  : _to_float(fd.get("rough_road_pct", 20)),
        "urban_route_pct"                 : _to_float(fd.get("urban_route_pct", 50)),
        "port_route_pct"                  : _to_float(fd.get("port_route_pct", 0)),
        "fuel_rate_lph"                   : _to_float(fd.get("fuel_rate_lph", 0)),
        "fuel_efficiency_km_per_l"        : _to_float(fd.get("fuel_efficiency_km_per_l", 0)),
        "engine_temp_avg_c"               : _to_float(fd.get("engine_temp_avg_c", 85)),
        "coolant_temp_max_c"              : _to_float(fd.get("coolant_temp_max_c", 95)),
        "vibration_rms_mm_s"              : _to_float(fd.get("vibration_rms_mm_s", 2.0)),
        "tire_pressure_psi"               : _to_float(fd.get("tire_pressure_psi", 72)),
        "battery_voltage_v"               : _to_float(fd.get("battery_voltage_v", 12.5)),
        "ambient_temp_avg_c"              : _to_float(fd.get("ambient_temp_avg_c", 30)),
        "ambient_humidity_avg_pct"        : _to_float(fd.get("ambient_humidity_avg_pct", 75)),
        "rainfall_mm_30d"                 : _to_float(fd.get("rainfall_mm_30d", 100)),
        "route_type"                      : str(fd.get("route_type") or "__missing__"),
        "cargo_type"                      : str(fd.get("cargo_type") or "__missing__"),
        "operating_shift"                 : str(fd.get("operating_shift") or "__missing__"),
        "maintenance_priority"            : str(asset.maintenance_priority or "Medium"),
        "service_provider_type"           : str(asset.service_provider_type or "in_house"),
        # Service type from sensor reading
        "last_service_type"               : str(fd.get("last_service_type") or "oil_service"),
        "next_service_type"               : None,  # not available at batch time
        "major_component_replaced"        : str(fd.get("major_component_replaced") or "none"),
        "parts_replaced_last_service"     : str(fd.get("parts_replaced_last_service") or ""),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Vectorized model inference — runs on a DataFrame of N assets at once
# ──────────────────────────────────────────────────────────────────────────────

def _run_classifier_batch(
    feature_dicts: list[dict[str, Any]],
    clf_model,
    clf_features: list[str],
    clf_threshold: float,
    clf_categorical_cols: list[str],
) -> list[tuple[float, bool]]:
    df = clf_model.build_frame(feature_dicts)
    try:
        probas = clf_model.predict_proba_positive(df)
        return [
            (round(float(p), 4), bool(p >= clf_threshold))
            for p in probas
        ]
    except Exception as e:
        log.warning("Batched LightGBM classification failed: %s. Falling back to per-row.", e)

    results = []
    for i in range(len(df)):
        try:
            prob = float(clf_model.predict_proba_positive(df.iloc[[i]])[0])
        except Exception:
            prob = 0.05
        results.append((round(prob, 4), bool(prob >= clf_threshold)))
    return results


def _run_regressor_batch(
    feature_dicts: list[dict[str, Any]],
    reg_model,
    reg_features: list[str],
    reg_categorical_cols: list[str],
    snapshot_date: date,
) -> list[tuple[int, date, list[dict], bool]]:
    df = reg_model.build_frame(feature_dicts)
    try:
        raw_days = reg_model.predict(df)
        shap_rows = reg_model.shap_top_factors(df, top_n=5)
        results = []
        for i in range(len(df)):
            raw = float(raw_days[i])
            saturated = raw >= REGRESSOR_HORIZON_DAYS
            days = int(np.clip(round(raw), 1, REGRESSOR_HORIZON_DAYS))
            pred_date = snapshot_date + timedelta(days=days)
            results.append((days, pred_date, shap_rows[i], saturated))
        return results
    except Exception as e:
        log.warning("Batched LightGBM regression/SHAP failed: %s. Falling back to plain predict.", e)

    raw_days = reg_model.predict(df)
    results = []
    for i in range(len(df)):
        raw = float(raw_days[i])
        saturated = raw >= REGRESSOR_HORIZON_DAYS
        days = int(np.clip(round(raw), 1, REGRESSOR_HORIZON_DAYS))
        pred_date = snapshot_date + timedelta(days=days)
        results.append((days, pred_date, [], saturated))
    return results


def _compute_health_score(fd: dict, failure_probability: float, days_until: float) -> tuple[float, str]:
    battery = _to_float(fd.get("battery_health_pct"))
    brake = _to_float(fd.get("brake_health_pct"))
    tire = _to_float(fd.get("tire_health_pct"))
    oil = _to_float(fd.get("oil_life_pct"))
    hydraulic = _to_float(fd.get("hydraulic_health_pct"))

    base = (battery + brake + tire + oil + hydraulic) / 5.0 if any([battery, brake, tire, oil, hydraulic]) else 60.0
    penalty = (failure_probability * 35.0) + max(0.0, (30.0 - min(days_until, 30.0))) * 0.5
    score = round(max(0.0, min(100.0, base - penalty)), 2)

    if score >= 85:
        status = "Healthy"
    elif score >= 70:
        status = "Good"
    elif score >= 50:
        status = "Moderate"
    elif score >= 30:
        status = "Poor"
    else:
        status = "Critical"

    return score, status


def _compute_contributing_factors(fd: dict, failure_probability: float) -> list[dict]:
    """Mirror the health score contributing factors from prediction_service.py."""
    factors = []
    factors.append({"feature": "brake_health_pct", "impact": round(_to_float(fd.get("brake_health_pct")) * 0.22, 4)})
    factors.append({"feature": "tire_health_pct", "impact": round(_to_float(fd.get("tire_health_pct")) * 0.18, 4)})
    factors.append({"feature": "oil_life_pct", "impact": round(_to_float(fd.get("oil_life_pct")) * 0.18, 4)})
    factors.append({"feature": "battery_health_pct", "impact": round(_to_float(fd.get("battery_health_pct")) * 0.15, 4)})
    factors.append({"feature": "hydraulic_health_pct", "impact": round(_to_float(fd.get("hydraulic_health_pct")) * 0.12, 4)})

    engine_temp = _to_float(fd.get("engine_temp_avg_c"))
    if engine_temp > 95:
        factors.append({"feature": "engine_temp_avg_c", "impact": -round(min((engine_temp - 95) * 0.8, 10), 4)})
    coolant_temp = _to_float(fd.get("coolant_temp_max_c"))
    if coolant_temp > 105:
        factors.append({"feature": "coolant_temp_max_c", "impact": -round(min((coolant_temp - 105) * 1.0, 10), 4)})
    vibration = _to_float(fd.get("vibration_rms_mm_s"))
    if vibration > 4.5:
        factors.append({"feature": "vibration_rms_mm_s", "impact": -round(min((vibration - 4.5) * 3.5, 15), 4)})
    fault_codes = _to_int(fd.get("active_fault_code_count"))
    if fault_codes > 0:
        factors.append({"feature": "active_fault_code_count", "impact": -round(min(fault_codes * 2.5, 12), 4)})
    days_svc = _to_int(fd.get("days_since_last_service"))
    if days_svc > 60:
        factors.append({"feature": "days_since_last_service", "impact": -round(min((days_svc - 60) * 0.08, 10), 4)})
    overloads = _to_int(fd.get("overload_events_30d"))
    if overloads > 0:
        factors.append({"feature": "overload_events_30d", "impact": -round(min(overloads * 1.8, 8), 4)})
    downtime = _to_float(fd.get("downtime_hours_last_90d"))
    if downtime > 0:
        factors.append({"feature": "downtime_hours_last_90d", "impact": -round(min(downtime * 0.5, 8), 4)})

    return sorted(factors, key=lambda x: abs(x["impact"]), reverse=True)[:8]


def _estimate_cost(
    fd: dict,
    failure_probability: float,
    days_until: float,
    asset: Asset | None = None,
    breakdown_cost_bundle: dict | None = None,
) -> tuple[float, float, float]:
    """Estimate maintenance cost.

    If breakdown_cost_bundle is provided, uses the v4 XGBoost model for an
    accurate data-driven estimate. Falls back to the heuristic formula if the
    model is unavailable or raises an exception — so existing behaviour is
    100% preserved when the bundle is not loaded.
    """
    if breakdown_cost_bundle is not None and asset is not None:
        try:
            from app.ai.models.cost_estimation_model.breakdown_cost_model import predict_breakdown_cost
            cost_input = _build_cost_input_from_fd(asset, fd)
            result = predict_breakdown_cost(cost_input, breakdown_cost_bundle, top_k=5)
            estimated = result["predicted_cost_lkr"]
            min_cost  = result["pi_80_lower_lkr"]
            max_cost  = result["pi_80_upper_lkr"]
            return round(estimated, 2), round(min_cost, 2), round(max_cost, 2)
        except Exception as exc:
            log.warning(
                "_estimate_cost: breakdown cost model failed for asset %s, "
                "falling back to heuristic: %s",
                str(getattr(asset, "id", "?"))[:8], exc,
            )

    # ── Heuristic fallback (original formula — unchanged) ─────────────────────
    base = 15_000.0
    vibration_factor  = _to_float(fd.get("vibration_rms_mm_s")) * 1_200.0
    fault_factor      = _to_int(fd.get("active_fault_code_count")) * 2_500.0
    downtime_factor   = _to_float(fd.get("downtime_hours_last_90d")) * 300.0
    urgency_factor    = max(0.0, (30.0 - min(days_until, 30.0))) * 250.0
    probability_factor = failure_probability * 22_000.0

    estimate = base + vibration_factor + fault_factor + downtime_factor + urgency_factor + probability_factor
    min_cost = max(5_000.0, estimate * 0.85)
    max_cost = estimate * 1.20
    return round(estimate, 2), round(min_cost, 2), round(max_cost, 2)


def _compute_risk_level(failure_probability: float, days_until: float) -> str:
    if failure_probability >= 0.8 or days_until <= 7:
        return "critical"
    if failure_probability >= 0.6 or days_until <= 14:
        return "high"
    if failure_probability >= 0.35 or days_until <= 30:
        return "medium"
    return "low"


# ──────────────────────────────────────────────────────────────────────────────
# DB access — batched fetch + batched upsert
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_latest_readings(db: Session, asset_ids: list[str]) -> dict[str, Any]:
    from app.models import SensorReading
    if not asset_ids:
        return {}
    rows = (
        db.query(SensorReading)
        .filter(SensorReading.asset_id.in_(asset_ids))
        .order_by(SensorReading.asset_id, SensorReading.recorded_at.desc())
        .distinct(SensorReading.asset_id)
        .all()
    )
    return {str(r.asset_id): r for r in rows}


_UPSERT_CHUNK_SIZE = 500


def _upsert_batch_predictions(db: Session, rows: list[dict]) -> None:
    if not rows:
        return
    for start in range(0, len(rows), _UPSERT_CHUNK_SIZE):
        _upsert_batch_predictions_chunk(db, rows[start:start + _UPSERT_CHUNK_SIZE])


_UPSERT_COLUMNS = [
    "failure_probability", "maintenance_required", "risk_level",
    "predicted_days_until_maintenance", "predicted_maintenance_date",
    "health_score", "health_status", "contributing_factors",
    "estimated_cost_lkr", "min_cost_lkr", "max_cost_lkr",
    "top_explanations",
    "run_duration_ms", "error_message", "status",
    "model_version", "feature_snapshot",
    "tier", "agreement", "display_mode", "horizon_text",
    "recommended_action", "horizon_saturated",
]
_JSONB_COLUMNS = {"contributing_factors", "top_explanations", "feature_snapshot"}


_HISTORY_COLUMNS = [
    "failure_probability", "predicted_days_until_maintenance",
    "predicted_maintenance_date", "health_score", "tier", "model_version",
]


def _log_prediction_history(db: Session, rows: list[dict]) -> None:
    if not rows:
        return
    try:
        values_sql = ", ".join(
            "(gen_random_uuid(), :asset_id_{i}, {cols}, now())".format(
                i=i, cols=", ".join(f":{c}_{i}" for c in _HISTORY_COLUMNS)
            )
            for i in range(len(rows))
        )
        params: dict[str, Any] = {}
        for i, payload in enumerate(rows):
            params[f"asset_id_{i}"] = payload["asset_id"]
            for c in _HISTORY_COLUMNS:
                params[f"{c}_{i}"] = payload.get(c)

        columns_sql = ", ".join(_HISTORY_COLUMNS)
        db.execute(
            text(f"""
                INSERT INTO pdm_prediction_history (
                    id, asset_id, {columns_sql}, predicted_at
                ) VALUES {values_sql}
            """),
            params,
        )
        db.commit()
    except Exception:
        db.rollback()
        log.warning("Prediction history logging failed (non-fatal) for %d rows", len(rows))


def _upsert_batch_predictions_chunk(db: Session, rows: list[dict]) -> None:
    def _value_expr(col: str, i: int) -> str:
        return f"CAST(:{col}_{i} AS jsonb)" if col in _JSONB_COLUMNS else f":{col}_{i}"

    values_sql = ", ".join(
        "(gen_random_uuid(), :asset_id_{i}, {cols}, now())".format(
            i=i, cols=", ".join(_value_expr(c, i) for c in _UPSERT_COLUMNS)
        )
        for i in range(len(rows))
    )

    params: dict[str, Any] = {}
    for i, payload in enumerate(rows):
        for key, value in payload.items():
            params[f"{key}_{i}"] = value

    columns_sql = ", ".join(_UPSERT_COLUMNS)
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPSERT_COLUMNS)

    sql = f"""
        INSERT INTO pdm_batch_predictions (
            id, asset_id, {columns_sql}, predicted_at
        ) VALUES {values_sql}
        ON CONFLICT (asset_id) DO UPDATE SET
            {update_sql},
            predicted_at = EXCLUDED.predicted_at
    """

    try:
        db.execute(text(sql), params)
        db.commit()
        _log_prediction_history(db, [r for r in rows if r.get("status") == "ok"])
    except Exception:
        db.rollback()
        log.warning("Batched upsert failed — falling back to per-row upsert for this run.")
        for payload in rows:
            asset_id = payload["asset_id"]
            try:
                _upsert_single(db, asset_id, {k: v for k, v in payload.items() if k != "asset_id"})
                db.commit()
                if payload.get("status") == "ok":
                    _log_prediction_history(db, [{**payload, "asset_id": asset_id}])
            except Exception:
                db.rollback()
                log.exception("Per-row upsert fallback also failed for asset %s", asset_id)


def _upsert_single(db: Session, asset_id: str, payload: dict) -> None:
    columns_sql = ", ".join(_UPSERT_COLUMNS)
    values_sql = ", ".join(
        f"CAST(:{c} AS jsonb)" if c in _JSONB_COLUMNS else f":{c}" for c in _UPSERT_COLUMNS
    )
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in _UPSERT_COLUMNS)

    db.execute(
        text(f"""
            INSERT INTO pdm_batch_predictions (
                id, asset_id, {columns_sql}, predicted_at
            ) VALUES (
                gen_random_uuid(), :asset_id, {values_sql}, now()
            )
            ON CONFLICT (asset_id) DO UPDATE SET
                {update_sql},
                predicted_at = EXCLUDED.predicted_at
        """),
        {**{c: payload.get(c) for c in _UPSERT_COLUMNS}, "asset_id": str(asset_id)},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def run_batch_for_asset(
    db: Session,
    asset: Asset,
    clf_model,
    clf_features: list[str],
    clf_threshold: float,
    clf_categorical_cols: list[str],
    reg_model,
    reg_features: list[str],
    reg_categorical_cols: list[str] = [],
    breakdown_cost_bundle: dict | None = None,
) -> dict:
    """Run the full PDM pipeline for a single asset and upsert the result.

    breakdown_cost_bundle is optional — when supplied, uses the v4 XGBoost
    model for cost estimation. When None, falls back to the heuristic formula
    (original behaviour, fully preserved).
    """
    start_ms = int(time.time() * 1000)
    asset_id_str = str(asset.id)

    try:
        readings = _fetch_latest_readings(db, [asset_id_str])
        reading = readings.get(asset_id_str)

        if reading is None:
            elapsed = int(time.time() * 1000) - start_ms
            _upsert_single(db, asset_id_str, {
                **_empty_prediction_fields(),
                "run_duration_ms": elapsed,
                "error_message": "No sensor reading found",
                "status": "no_data",
            })
            db.commit()
            log.warning("[batch] asset %s — no sensor reading, skipped", asset_id_str[:8])
            return {"asset_id": asset_id_str, "status": "no_data"}

        today = date.today()
        fd = _build_feature_dict(asset, reading, snapshot_date=today)

        (failure_probability, maintenance_required), = _run_classifier_batch(
            [fd], clf_model, clf_features, clf_threshold, clf_categorical_cols
        )
        (days_until, pred_date, top_explanations, horizon_saturated), = _run_regressor_batch(
            [fd], reg_model, reg_features, reg_categorical_cols, today
        )
        health_score, health_status = _compute_health_score(fd, failure_probability, days_until)
        contributing_factors = _compute_contributing_factors(fd, failure_probability)
        estimated_cost, min_cost, max_cost = _estimate_cost(
            fd, failure_probability, days_until,
            asset=asset,
            breakdown_cost_bundle=breakdown_cost_bundle,
        )
        risk_level = _compute_risk_level(failure_probability, days_until)
        decision = build_decision(
            failure_probability=failure_probability,
            maintenance_required=maintenance_required,
            days_until_maintenance=days_until,
            predicted_maintenance_date=pred_date,
            health_score=health_score,
            horizon_saturated=horizon_saturated,
            clf_threshold=clf_threshold,
        )

        elapsed = int(time.time() * 1000) - start_ms
        _upsert_single(db, asset_id_str, {
            "failure_probability": failure_probability,
            "maintenance_required": maintenance_required,
            "risk_level": risk_level,
            "predicted_days_until_maintenance": days_until,
            "predicted_maintenance_date": pred_date.isoformat(),
            "health_score": health_score,
            "health_status": health_status,
            "contributing_factors": json.dumps(contributing_factors),
            "estimated_cost_lkr": estimated_cost,
            "min_cost_lkr": min_cost,
            "max_cost_lkr": max_cost,
            "top_explanations": json.dumps(top_explanations),
            "run_duration_ms": elapsed,
            "error_message": None,
            "status": "ok",
            "model_version": _model_version_tag(),
            "feature_snapshot": json.dumps(fd),
            "tier": decision["tier"],
            "agreement": decision["agreement"],
            "display_mode": decision["display_mode"],
            "horizon_text": decision["horizon_text"],
            "recommended_action": decision["recommended_action"],
            "horizon_saturated": decision["horizon_saturated"],
        })
        db.commit()
        _log_prediction_history(db, [{
            "asset_id": asset_id_str,
            "failure_probability": failure_probability,
            "predicted_days_until_maintenance": days_until,
            "predicted_maintenance_date": pred_date.isoformat(),
            "health_score": health_score,
            "tier": decision["tier"],
            "model_version": _model_version_tag(),
        }])

        log.info(
            "[batch] asset %s (%s) — prob=%.3f days=%d health=%.1f cost=%.0f tier=%s [%dms]",
            asset_id_str[:8],
            asset.asset_code or "?",
            failure_probability,
            days_until,
            health_score,
            estimated_cost,
            decision["tier"],
            elapsed,
        )
        return {
            "asset_id": asset_id_str,
            "status": "ok",
            "failure_probability": failure_probability,
            "risk_level": risk_level,
            "health_score": health_score,
            "days_until_maintenance": days_until,
            "tier": decision["tier"],
        }

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        elapsed = int(time.time() * 1000) - start_ms
        error_msg = str(exc)[:500]
        log.exception("[batch] asset %s failed: %s", asset_id_str[:8], error_msg)

        try:
            _upsert_single(db, asset_id_str, {
                **_empty_prediction_fields(),
                "run_duration_ms": elapsed,
                "error_message": error_msg,
                "status": "error",
            })
            db.commit()
        except Exception:
            db.rollback()

        return {"asset_id": asset_id_str, "status": "error", "error": error_msg}


def run_batch_for_all_assets(
    db: Session,
    clf_model,
    clf_features: list[str],
    clf_threshold: float,
    clf_categorical_cols: list[str],
    reg_model,
    reg_features: list[str],
    reg_categorical_cols: list[str] = [],
    breakdown_cost_bundle: dict | None = None,
) -> dict:
    """Run the full PDM batch for every active asset.

    breakdown_cost_bundle is optional — when supplied, uses the v4 XGBoost
    model for cost estimation instead of the heuristic formula.
    Fully backward-compatible: passing None preserves the original behaviour.
    """
    if clf_model is None or reg_model is None:
        log.warning("[batch] Models not loaded — skipping batch run")
        return {"status": "skipped", "reason": "models_not_loaded"}

    run_start = time.time()
    log.info("[batch] Starting PDM batch run…")

    assets = (
        db.query(Asset)
        .filter(cast(Asset.status, String) != "decommissioned")
        .order_by(Asset.asset_code)
        .all()
    )

    total = len(assets)
    if total == 0:
        elapsed = round(time.time() - run_start, 2)
        return {
            "status": "completed",
            "total_assets": 0,
            "ok": 0,
            "no_data": 0,
            "errors": 0,
            "elapsed_seconds": elapsed,
            "run_at": datetime.utcnow().isoformat(),
        }

    asset_ids = [str(a.id) for a in assets]
    readings_by_asset = _fetch_latest_readings(db, asset_ids)
    today = date.today()

    ok_count = 0
    no_data_count = 0
    error_count = 0
    upsert_rows: list[dict] = []

    scored_assets: list[Asset] = []
    feature_dicts: list[dict[str, Any]] = []

    for asset in assets:
        asset_id_str = str(asset.id)
        reading = readings_by_asset.get(asset_id_str)
        if reading is None:
            no_data_count += 1
            upsert_rows.append({
                "asset_id": asset_id_str,
                **_empty_prediction_fields(),
                "run_duration_ms": 0,
                "error_message": "No sensor reading found",
                "status": "no_data",
            })
            continue

        try:
            fd = _build_feature_dict(asset, reading, snapshot_date=today)
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            error_msg = str(exc)[:500]
            log.exception("[batch] asset %s — feature build failed: %s", asset_id_str[:8], error_msg)
            upsert_rows.append({
                "asset_id": asset_id_str,
                **_empty_prediction_fields(),
                "run_duration_ms": 0,
                "error_message": error_msg,
                "status": "error",
            })
            continue

        scored_assets.append(asset)
        feature_dicts.append(fd)

    if feature_dicts:
        try:
            classifier_results = _run_classifier_batch(
                feature_dicts, clf_model, clf_features, clf_threshold, clf_categorical_cols
            )
            regressor_results = _run_regressor_batch(
                feature_dicts, reg_model, reg_features, reg_categorical_cols, today
            )
            model_version = _model_version_tag()

            for asset, fd, (failure_probability, maintenance_required), (days_until, pred_date, top_explanations, horizon_saturated) in zip(
                scored_assets, feature_dicts, classifier_results, regressor_results
            ):
                asset_id_str = str(asset.id)
                health_score, health_status = _compute_health_score(fd, failure_probability, days_until)
                contributing_factors = _compute_contributing_factors(fd, failure_probability)
                estimated_cost, min_cost, max_cost = _estimate_cost(
                    fd, failure_probability, days_until,
                    asset=asset,
                    breakdown_cost_bundle=breakdown_cost_bundle,
                )
                risk_level = _compute_risk_level(failure_probability, days_until)
                decision = build_decision(
                    failure_probability=failure_probability,
                    maintenance_required=maintenance_required,
                    days_until_maintenance=days_until,
                    predicted_maintenance_date=pred_date,
                    health_score=health_score,
                    horizon_saturated=horizon_saturated,
                    clf_threshold=clf_threshold,
                )

                ok_count += 1
                upsert_rows.append({
                    "asset_id": asset_id_str,
                    "failure_probability": failure_probability,
                    "maintenance_required": maintenance_required,
                    "risk_level": risk_level,
                    "predicted_days_until_maintenance": days_until,
                    "predicted_maintenance_date": pred_date.isoformat(),
                    "health_score": health_score,
                    "health_status": health_status,
                    "contributing_factors": json.dumps(contributing_factors),
                    "estimated_cost_lkr": estimated_cost,
                    "min_cost_lkr": min_cost,
                    "max_cost_lkr": max_cost,
                    "top_explanations": json.dumps(top_explanations),
                    "run_duration_ms": 0,
                    "error_message": None,
                    "status": "ok",
                    "model_version": model_version,
                    "feature_snapshot": json.dumps(fd),
                    "tier": decision["tier"],
                    "agreement": decision["agreement"],
                    "display_mode": decision["display_mode"],
                    "horizon_text": decision["horizon_text"],
                    "recommended_action": decision["recommended_action"],
                    "horizon_saturated": decision["horizon_saturated"],
                })

                log.info(
                    "[batch] asset %s (%s) — prob=%.3f days=%d health=%.1f cost=%.0f tier=%s",
                    asset_id_str[:8], asset.asset_code or "?",
                    failure_probability, days_until, health_score, estimated_cost, decision["tier"],
                )
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)[:500]
            log.exception("[batch] vectorized inference failed, falling back to per-asset: %s", error_msg)
            for asset in scored_assets:
                result = run_batch_for_asset(
                    db=db,
                    asset=asset,
                    clf_model=clf_model,
                    clf_features=clf_features,
                    clf_threshold=clf_threshold,
                    clf_categorical_cols=clf_categorical_cols,
                    reg_model=reg_model,
                    reg_features=reg_features,
                    reg_categorical_cols=reg_categorical_cols,
                    breakdown_cost_bundle=breakdown_cost_bundle,
                )
                s = result.get("status")
                if s == "ok":
                    ok_count += 1
                elif s == "no_data":
                    no_data_count += 1
                else:
                    error_count += 1
            feature_dicts = []
            upsert_rows = [r for r in upsert_rows if r["asset_id"] not in {str(a.id) for a in scored_assets}]

    _upsert_batch_predictions(db, upsert_rows)

    elapsed = round(time.time() - run_start, 2)
    log.info(
        "[batch] Completed in %.1fs — %d ok / %d no_data / %d errors (total=%d)",
        elapsed, ok_count, no_data_count, error_count, total,
    )

    return {
        "status": "completed",
        "total_assets": total,
        "ok": ok_count,
        "no_data": no_data_count,
        "errors": error_count,
        "elapsed_seconds": elapsed,
        "run_at": datetime.utcnow().isoformat(),
    }