"""Batch PDM prediction service.

Runs the full PDM pipeline (classification, regression, health score, cost
estimation) for **every active asset** and upserts one row per asset into the
``pdm_batch_predictions`` table.

Designed to be invoked:
 - By the APScheduler inside FastAPI every hour (started in ``main.py``).
 - Via the ``POST /batch-predictions/run`` REST endpoint for manual triggers.
 - Via the ``POST /batch-predictions/run/{asset_id}`` endpoint for a single asset.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, text
from sqlalchemy.orm import Session

from app.models import Asset, PdmBatchPrediction

log = logging.getLogger("predictix.batch")

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
# Internal helpers (mirror vehicle_prediction_service without the DB write loop)
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


def _build_feature_dict(asset: Asset, reading) -> dict[str, Any]:
    """Build the feature dict from an Asset ORM row + its latest SensorReading."""
    fd: dict[str, Any] = {}

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

    # All sensor/engineered features from SensorReading
    sensor_float_cols = [
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
    ]
    sensor_int_cols = [
        "days_since_last_service",
        "active_fault_code_count",
        "trip_count_30d",
        "overload_events_30d",
        "start_stop_burden_30d",
    ]
    sensor_bool_cols = [
        "sensor_fault_flag",
        "is_home_warehouse_service",
    ]
    sensor_str_cols = [
        "route_type",
        "cargo_type",
        "operating_shift",
        "last_service_type",
        "parts_replaced_last_service",
        "major_component_replaced",
    ]

    for col in sensor_float_cols:
        fd[col] = _to_float(getattr(reading, col, None))
    for col in sensor_int_cols:
        fd[col] = _to_int(getattr(reading, col, None))
    for col in sensor_bool_cols:
        val = getattr(reading, col, None)
        fd[col] = bool(val) if val is not None else False
    for col in sensor_str_cols:
        fd[col] = str(getattr(reading, col, None) or "")

    return fd


def _run_classifier(fd: dict, clf_model, clf_features: list[str], clf_threshold: float, clf_categorical_cols: list[str]) -> tuple[float, bool]:
    """Returns (failure_probability, maintenance_required).

    The XGBoost v6 model was trained with `enable_categorical=True`, so
    categorical columns must be passed as pandas Categorical dtype (not str/object).
    """
    import pandas as pd

    cat_set = set(clf_categorical_cols or [])
    row = {f: fd.get(f, "") if f in cat_set else fd.get(f, 0)
           for f in clf_features}
    df = pd.DataFrame([row])

    for col in df.columns:
        if col in cat_set:
            df[col] = pd.Categorical([df[col].iloc[0]])
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    try:
        probas = clf_model.predict_proba(df)[0]
        prob = float(probas[-1]) if len(probas) > 1 else float(probas[0])
    except Exception as e:
        import logging
        logging.getLogger("predictix.ai").warning(f"XGBoost classification failed (likely unknown category): {e}. Falling back to 0.05.")
        prob = 0.05

    return round(prob, 4), bool(prob >= clf_threshold)







def _run_regressor(fd: dict, reg_model, reg_features: list[str], snapshot_date: date) -> tuple[int, date, list[dict]]:
    """Returns (days_until_maintenance, predicted_date, top_explanations).

    CatBoost categorical features must be strings (not numeric).  We detect
    them from the model's stored cat_feature_indices and ensure the right
    columns are str before building the Pool.
    """
    import numpy as np
    import pandas as pd
    from catboost import Pool

    # Determine which of the reg_features are categoricals from the model
    try:
        cat_indices_from_model = reg_model.get_cat_feature_indices() or []
    except Exception:
        cat_indices_from_model = []

    cat_feature_names = {reg_features[i] for i in cat_indices_from_model if i < len(reg_features)}

    row = {f: fd.get(f, "") if f in cat_feature_names else fd.get(f, 0)
           for f in reg_features}
    df = pd.DataFrame([row])

    for col in df.columns:
        if col in cat_feature_names:
            df[col] = df[col].astype(str)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    cat_indices = [df.columns.get_loc(c) for c in cat_feature_names if c in df.columns]

    try:
        pool = Pool(df, cat_features=cat_indices)
        raw_days = float(reg_model.predict(pool)[0])

        # SHAP explanations from CatBoost
        shap_vals = reg_model.get_feature_importance(type="ShapValues", data=pool)
        row_shap = shap_vals[0][:-1]
        ranked = sorted(zip(list(df.columns), row_shap), key=lambda x: abs(x[1]), reverse=True)
        top_explanations = [
            {"feature": feat, "impact": round(float(imp), 4)}
            for feat, imp in ranked[:5]
        ]
    except Exception:
        # Fallback: plain predict if Pool construction fails
        raw_days = float(reg_model.predict(df)[0])
        top_explanations = []

    days = int(np.clip(round(raw_days), 1, 180))
    pred_date = snapshot_date + timedelta(days=days)

    return days, pred_date, top_explanations




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

    # Positive contributions (weighted component health)
    factors.append({"feature": "brake_health_pct", "impact": round(_to_float(fd.get("brake_health_pct")) * 0.22, 4)})
    factors.append({"feature": "tire_health_pct", "impact": round(_to_float(fd.get("tire_health_pct")) * 0.18, 4)})
    factors.append({"feature": "oil_life_pct", "impact": round(_to_float(fd.get("oil_life_pct")) * 0.18, 4)})
    factors.append({"feature": "battery_health_pct", "impact": round(_to_float(fd.get("battery_health_pct")) * 0.15, 4)})
    factors.append({"feature": "hydraulic_health_pct", "impact": round(_to_float(fd.get("hydraulic_health_pct")) * 0.12, 4)})

    # Penalties
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


def _estimate_cost(fd: dict, failure_probability: float, days_until: float) -> tuple[float, float, float]:
    base = 15_000.0
    vibration_factor = _to_float(fd.get("vibration_rms_mm_s")) * 1_200.0
    fault_factor = _to_int(fd.get("active_fault_code_count")) * 2_500.0
    downtime_factor = _to_float(fd.get("downtime_hours_last_90d")) * 300.0
    urgency_factor = max(0.0, (30.0 - min(days_until, 30.0))) * 250.0
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
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def _upsert_batch_prediction(db: Session, asset_id: str, payload: dict) -> None:
    """Insert or update (upsert) one row in pdm_batch_predictions."""
    db.execute(
        text("""
            INSERT INTO pdm_batch_predictions (
                id, asset_id,
                failure_probability, maintenance_required, risk_level,
                predicted_days_until_maintenance, predicted_maintenance_date,
                health_score, health_status, contributing_factors,
                estimated_cost_lkr, min_cost_lkr, max_cost_lkr,
                top_explanations,
                predicted_at, run_duration_ms, error_message, status
            ) VALUES (
                gen_random_uuid(), :asset_id,
                :failure_probability, :maintenance_required, :risk_level,
                :predicted_days_until_maintenance, :predicted_maintenance_date,
                :health_score, :health_status, CAST(:contributing_factors AS jsonb),
                :estimated_cost_lkr, :min_cost_lkr, :max_cost_lkr,
                CAST(:top_explanations AS jsonb),
                now(), :run_duration_ms, :error_message, :status
            )
            ON CONFLICT (asset_id) DO UPDATE SET
                failure_probability               = EXCLUDED.failure_probability,
                maintenance_required              = EXCLUDED.maintenance_required,
                risk_level                        = EXCLUDED.risk_level,
                predicted_days_until_maintenance  = EXCLUDED.predicted_days_until_maintenance,
                predicted_maintenance_date        = EXCLUDED.predicted_maintenance_date,
                health_score                      = EXCLUDED.health_score,
                health_status                     = EXCLUDED.health_status,
                contributing_factors              = EXCLUDED.contributing_factors,
                estimated_cost_lkr                = EXCLUDED.estimated_cost_lkr,
                min_cost_lkr                      = EXCLUDED.min_cost_lkr,
                max_cost_lkr                      = EXCLUDED.max_cost_lkr,
                top_explanations                  = EXCLUDED.top_explanations,
                predicted_at                      = EXCLUDED.predicted_at,
                run_duration_ms                   = EXCLUDED.run_duration_ms,
                error_message                     = EXCLUDED.error_message,
                status                            = EXCLUDED.status
        """),
        {**payload, "asset_id": str(asset_id)},
    )


def run_batch_for_asset(
    db: Session,
    asset: Asset,
    clf_model,
    clf_features: list[str],
    clf_threshold: float,
    clf_categorical_cols: list[str],
    reg_model,
    reg_features: list[str],
) -> dict:
    """Run the full PDM pipeline for a single asset and upsert the result.

    Returns a summary dict with the prediction outcome (or error info).
    """
    from app.models import SensorReading

    start_ms = int(time.time() * 1000)
    asset_id_str = str(asset.id)

    try:
        # Fetch latest sensor reading
        reading = (
            db.query(SensorReading)
            .filter(SensorReading.asset_id == asset.id)
            .order_by(SensorReading.recorded_at.desc())
            .first()
        )

        if reading is None:
            elapsed = int(time.time() * 1000) - start_ms
            _upsert_batch_prediction(db, asset_id_str, {
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
                "run_duration_ms": elapsed,
                "error_message": "No sensor reading found",
                "status": "no_data",
            })
            db.commit()
            log.warning("[batch] asset %s — no sensor reading, skipped", asset_id_str[:8])
            return {"asset_id": asset_id_str, "status": "no_data"}

        fd = _build_feature_dict(asset, reading)
        today = date.today()

        # Run models
        failure_probability, maintenance_required = _run_classifier(
            fd, clf_model, clf_features, clf_threshold, clf_categorical_cols
        )
        days_until, pred_date, top_explanations = _run_regressor(
            fd, reg_model, reg_features, today
        )
        health_score, health_status = _compute_health_score(fd, failure_probability, days_until)
        contributing_factors = _compute_contributing_factors(fd, failure_probability)
        estimated_cost, min_cost, max_cost = _estimate_cost(fd, failure_probability, days_until)
        risk_level = _compute_risk_level(failure_probability, days_until)

        import json
        elapsed = int(time.time() * 1000) - start_ms
        _upsert_batch_prediction(db, asset_id_str, {
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
        })
        db.commit()

        log.info(
            "[batch] asset %s (%s) — prob=%.3f days=%d health=%.1f cost=%.0f [%dms]",
            asset_id_str[:8],
            asset.asset_code or "?",
            failure_probability,
            days_until,
            health_score,
            estimated_cost,
            elapsed,
        )
        return {
            "asset_id": asset_id_str,
            "status": "ok",
            "failure_probability": failure_probability,
            "risk_level": risk_level,
            "health_score": health_score,
            "days_until_maintenance": days_until,
        }

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        elapsed = int(time.time() * 1000) - start_ms
        error_msg = str(exc)[:500]
        log.exception("[batch] asset %s failed: %s", asset_id_str[:8], error_msg)

        try:
            import json
            _upsert_batch_prediction(db, asset_id_str, {
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
) -> dict:
    """Run the full PDM batch for every active asset.

    Called by the APScheduler every hour and by the manual trigger endpoint.
    Returns a summary dict with counts.
    """
    if clf_model is None or reg_model is None:
        log.warning("[batch] Models not loaded — skipping batch run")
        return {"status": "skipped", "reason": "models_not_loaded"}

    run_start = time.time()
    log.info("[batch] Starting hourly PDM batch run…")

    assets = (
        db.query(Asset)
        .filter(cast(Asset.status, String) == "active")
        .order_by(Asset.asset_code)
        .all()
    )

    total = len(assets)
    ok_count = error_count = no_data_count = 0

    for asset in assets:
        result = run_batch_for_asset(
            db=db,
            asset=asset,
            clf_model=clf_model,
            clf_features=clf_features,
            clf_threshold=clf_threshold,
            clf_categorical_cols=clf_categorical_cols,
            reg_model=reg_model,
            reg_features=reg_features,
        )
        s = result.get("status")
        if s == "ok":
            ok_count += 1
        elif s == "no_data":
            no_data_count += 1
        else:
            error_count += 1

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
