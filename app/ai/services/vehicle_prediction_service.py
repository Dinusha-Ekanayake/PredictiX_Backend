from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
import uuid

import pandas as pd
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    SensorReading,
    ModelRegistry,
    PredictionRun,
    AssetFailurePrediction,
    AssetCostPrediction,
)
from app.services.in_app_notification_service import InAppNotificationService


CLASSIFIER_MODEL_NAME = "pdm_classifier_model"
REGRESSOR_MODEL_NAME = "pdm_regressor_model"


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


def _get_latest_sensor_reading(db: Session, asset_id: str):
    return (
        db.query(SensorReading)
        .filter(SensorReading.asset_id == asset_id)
        .order_by(SensorReading.recorded_at.desc())
        .first()
    )


def _get_asset(db: Session, asset_id: str):
    return db.query(Asset).filter(Asset.id == asset_id).first()


def _get_model_registry(db: Session, model_name: str):
    return (
        db.query(ModelRegistry)
        .filter(ModelRegistry.model_name == model_name)
        .order_by(ModelRegistry.created_at.desc())
        .first()
    )


def build_vehicle_feature_dict(db: Session, asset_id: str) -> dict[str, Any]:
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    reading = _get_latest_sensor_reading(db, asset_id)
    if not reading:
        # Provide a mock reading for new assets without telemetry data
        class EmptyReading:
            pass
        reading = EmptyReading()

    feature_dict: dict[str, Any] = {}

    # ── Asset-level string (categorical) features ─────────────────────────────
    feature_dict["vehicle_type"]        = str(asset.vehicle_type or "")
    feature_dict["vehicle_role"]        = str(asset.vehicle_role or asset.vehicle_type or "transport")
    feature_dict["make_model"]          = str(asset.make_model or "")
    feature_dict["fuel_type"]           = str(asset.fuel_type or "")
    feature_dict["transmission"]        = str(asset.transmission or "")
    feature_dict["maintenance_priority"] = str(asset.maintenance_priority or "")
    feature_dict["service_provider_type"] = str(asset.service_provider_type or "")

    # ── Asset-level numeric features ──────────────────────────────────────────
    feature_dict["payload_capacity_kg"]      = _to_float(asset.payload_capacity_kg)
    feature_dict["vehicle_age_years"]        = _to_int(asset.vehicle_age_years)
    feature_dict["manufacture_year"]         = _to_int(asset.manufacture_year)
    feature_dict["lifetime_service_count"]   = _to_int(asset.lifetime_service_count)
    feature_dict["lifetime_breakdown_count"] = _to_int(asset.lifetime_breakdown_count)

    # ── Sensor / engineered numeric columns ───────────────────────────────────
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
        "urban_route_pct",
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
        feature_dict[col] = _to_float(getattr(reading, col, None))
    for col in sensor_int_cols:
        feature_dict[col] = _to_int(getattr(reading, col, None))
    for col in sensor_bool_cols:
        val = getattr(reading, col, None)
        feature_dict[col] = bool(val) if val is not None else False
    for col in sensor_str_cols:
        feature_dict[col] = str(getattr(reading, col, None) or "")

    return feature_dict


def build_dataframe_for_features(
    feature_dict: dict[str, Any],
    feature_names: list[str],
    categorical_cols: list[str] | None = None,
) -> pd.DataFrame:
    """
    Build a properly-typed DataFrame for XGBoost / CatBoost inference.

    - Columns in ``categorical_cols`` are cast to ``pd.Categorical``.
    - Any remaining column that still has ``object`` dtype is also cast to
      ``pd.Categorical`` as a safety-net — XGBoost trained with
      ``enable_categorical=True`` rejects object columns outright.
    - All other columns are coerced to numeric (float64).
    """
    cat_set = set(categorical_cols or [])
    row = {
        f: feature_dict.get(f, "" if f in cat_set else 0)
        for f in feature_names
    }
    df = pd.DataFrame([row])

    for col in df.columns:
        if col in cat_set:
            df[col] = pd.Categorical([str(df[col].iloc[0]).lower()])
        else:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.isna().all():
                # Could not convert at all — treat as categorical
                df[col] = pd.Categorical([str(df[col].iloc[0]).lower()])
            else:
                df[col] = converted.fillna(0)

    # Final safety pass: cast any remaining object columns to Categorical
    # (covers columns in clf_categorical_cols that were not in our explicit list)
    for col in df.select_dtypes(include="object").columns:
        df[col] = pd.Categorical(df[col].astype(str).str.lower())

    return df


def compute_health_score(feature_dict: dict[str, Any], failure_probability: float, days_until: float) -> tuple[float, str]:
    battery = feature_dict.get("battery_health_pct", 0.0) or 0.0
    brake = feature_dict.get("brake_health_pct", 0.0) or 0.0
    tire = feature_dict.get("tire_health_pct", 0.0) or 0.0
    oil = feature_dict.get("oil_life_pct", 0.0) or 0.0
    hydraulic = feature_dict.get("hydraulic_health_pct", 0.0) or 0.0

    base = (battery + brake + tire + oil + hydraulic) / 5.0 if any([battery, brake, tire, oil, hydraulic]) else 60.0
    penalty = (failure_probability * 35.0) + max(0.0, (30.0 - min(days_until, 30.0))) * 0.5
    health_score = max(0.0, min(100.0, base - penalty))

    if health_score >= 85:
        band = "excellent"
    elif health_score >= 70:
        band = "good"
    elif health_score >= 50:
        band = "moderate"
    elif health_score >= 30:
        band = "poor"
    else:
        band = "critical"

    return round(health_score, 2), band


def compute_risk_level(failure_probability: float, days_until: float) -> str:
    if failure_probability >= 0.8 or days_until <= 7:
        return "critical"
    if failure_probability >= 0.6 or days_until <= 14:
        return "high"
    if failure_probability >= 0.35 or days_until <= 30:
        return "medium"
    return "low"


def estimate_cost(feature_dict: dict[str, Any], failure_probability: float, days_until: float) -> tuple[float, float, float]:
    base_cost = 15000.0
    vibration_factor = _to_float(feature_dict.get("vibration_rms_mm_s")) * 1200.0
    fault_factor = _to_int(feature_dict.get("active_fault_code_count")) * 2500.0
    downtime_factor = _to_float(feature_dict.get("downtime_hours_last_90d")) * 300.0
    urgency_factor = max(0.0, (30.0 - min(days_until, 30.0))) * 250.0
    probability_factor = failure_probability * 22000.0

    estimate = base_cost + vibration_factor + fault_factor + downtime_factor + urgency_factor + probability_factor
    min_cost = max(5000.0, estimate * 0.85)
    max_cost = estimate * 1.20

    return round(estimate, 2), round(min_cost, 2), round(max_cost, 2)


def run_vehicle_prediction_and_store(
    db: Session,
    asset_id: str,
    requested_by: str | None,
    clf_model,
    clf_features: list[str],
    reg_model,
    reg_features: list[str],
    clf_categorical_cols: list[str] | None = None,
) -> dict[str, Any]:
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    feature_dict = build_vehicle_feature_dict(db, asset_id)

    clf_df = build_dataframe_for_features(feature_dict, clf_features, categorical_cols=clf_categorical_cols)
    reg_df = build_dataframe_for_features(feature_dict, reg_features, categorical_cols=None)

    try:
        predicted_class = int(clf_model.predict(clf_df)[0])
        if hasattr(clf_model, "predict_proba"):
            probas = clf_model.predict_proba(clf_df)[0]
            failure_probability = float(probas[-1]) if len(probas) > 1 else float(probas[0])
            confidence = float(max(probas))
        else:
            failure_probability = float(predicted_class)
            confidence = 0.75
    except Exception as e:
        import logging
        logging.getLogger("predictix.ai").warning(f"XGBoost classification failed (likely unknown category): {e}. Falling back to 0.05.")
        predicted_class = 0
        failure_probability = 0.05
        confidence = 0.75

    # regressor
    predicted_days_until = float(reg_model.predict(reg_df)[0])
    predicted_days_until = max(0.0, round(predicted_days_until, 2))

    predicted_maintenance_date = date.today() + timedelta(days=int(round(predicted_days_until)))
    health_score, health_band = compute_health_score(feature_dict, failure_probability, predicted_days_until)
    risk_level = compute_risk_level(failure_probability, predicted_days_until)
    estimated_cost, min_cost, max_cost = estimate_cost(feature_dict, failure_probability, predicted_days_until)

    clf_registry = _get_model_registry(db, CLASSIFIER_MODEL_NAME)
    if not clf_registry:
        raise ValueError(f"Model registry entry not found for {CLASSIFIER_MODEL_NAME}")

    run = PredictionRun(
        id=uuid.uuid4(),
        model_id=clf_registry.id,
        asset_id=asset.id,
        ticket_id=None,
        input_snapshot=feature_dict,
        requested_by=requested_by,
        run_started_at=datetime.utcnow(),
        run_finished_at=datetime.utcnow(),
        status="completed",
        error_message=None,
    )
    db.add(run)
    db.flush()

    failure_row = AssetFailurePrediction(
        id=uuid.uuid4(),
        run_id=run.id,
        asset_id=asset.id,
        health_score=health_score,
        failure_probability=round(failure_probability, 4),
        confidence=round(confidence, 4),
        risk_level=risk_level,
        predicted_maintenance_date=predicted_maintenance_date,
        days_until_maintenance=int(round(predicted_days_until)),
        top_explanations={
            "top_factors": [
                {"feature": "vibration_rms_mm_s", "value": feature_dict.get("vibration_rms_mm_s")},
                {"feature": "active_fault_code_count", "value": feature_dict.get("active_fault_code_count")},
                {"feature": "days_since_last_service", "value": feature_dict.get("days_since_last_service")},
            ]
        },
    )
    db.add(failure_row)

    cost_row = AssetCostPrediction(
        id=uuid.uuid4(),
        run_id=run.id,
        asset_id=asset.id,
        estimated_cost=estimated_cost,
        min_cost=min_cost,
        max_cost=max_cost,
        currency="LKR",
        confidence_score=round(confidence, 4),
    )
    db.add(cost_row)

    db.commit()
    db.refresh(run)
    db.refresh(failure_row)
    db.refresh(cost_row)

    if failure_probability >= 0.80:
        try:
            InAppNotificationService.notify_admins(
                db=db,
                title="Critical Asset Risk Detected",
                message=f"CRITICAL: Asset {asset.asset_code} has spiked to {round(failure_probability * 100, 1)}% failure probability.",
                priority="critical",
                notification_type="admin_alert",
                link_url=f"/admin/assets/{asset.id}"
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to send critical asset alert: %s", exc)

    return {
        "run_id": str(run.id),
        "asset_id": str(asset.id),
        "predicted_class": predicted_class,
        "predicted_label": "maintenance_required" if predicted_class == 1 else "maintenance_not_required",
        "failure_probability": round(failure_probability, 4),
        "confidence": round(confidence, 4),
        "predicted_days_until_maintenance": predicted_days_until,
        "predicted_maintenance_date": str(predicted_maintenance_date),
        "health_score": health_score,
        "health_band": health_band,
        "risk_level": risk_level,
        "estimated_cost_lkr": estimated_cost,
        "min_cost_lkr": min_cost,
        "max_cost_lkr": max_cost,
        "features_used": feature_dict,
    }