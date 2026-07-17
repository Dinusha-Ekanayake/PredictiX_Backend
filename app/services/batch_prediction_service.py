"""
PredictiX — Batch Prediction Service
app/ai/services/batch_prediction_service.py

Runs failure classification, RUL regression, health scoring, and cost
estimation (v3 CatBoost) for every active asset in the warehouse.
Called by _run_scheduled_batch() in main.py on a timer, and optionally
on startup via BATCH_RUN_ON_STARTUP=true.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

log = logging.getLogger("predictix")


def _build_cost_input(asset, last_event) -> dict:
    """
    Build raw_input dict for predict_cost() from Asset + MaintenanceEvent ORM rows.
    Identical to _build_cost_input() in predictions.py — kept in sync manually.
    """
    return {
        "vehicle_type"                    : asset.vehicle_type,
        "vehicle_role"                    : getattr(asset, "vehicle_role", None),
        "make_model"                      : getattr(asset, "make_model", None),
        "fuel_type"                       : getattr(asset, "fuel_type", None),
        "transmission"                    : getattr(asset, "transmission", None),
        "manufacture_year"                : getattr(asset, "manufacture_year", None),
        "vehicle_age_years"               : getattr(asset, "vehicle_age_years", 0),
        "payload_capacity_kg"             : getattr(asset, "payload_capacity_kg", 0),
        "odometer_km"                     : getattr(asset, "current_mileage", 0),
        "engine_hours_total"              : getattr(asset, "engine_hours_total", 0),
        "lifetime_service_count"          : getattr(asset, "lifetime_service_count", 0),
        "lifetime_breakdown_count"        : getattr(asset, "lifetime_breakdown_count", 0),
        "oil_life_pct"                    : getattr(asset, "oil_life_pct", 50),
        "brake_health_pct"                : getattr(asset, "brake_health_pct", 50),
        "tire_health_pct"                 : getattr(asset, "tire_health_pct", 50),
        "battery_health_pct"              : getattr(asset, "battery_health_pct", 50),
        "hydraulic_health_pct"            : getattr(asset, "hydraulic_health_pct", 50),
        "active_fault_code_count"         : getattr(asset, "active_fault_code_count", 0),
        "sensor_fault_flag"               : getattr(asset, "sensor_fault_flag", 0),
        "fuel_price_lkr_per_l"            : getattr(asset, "fuel_price_lkr_per_l", 310.0),
        "downtime_hours_last_90d"         : getattr(asset, "downtime_hours_last_90d", 0),
        "payload_utilization_pct"         : getattr(asset, "payload_utilization_pct", 50),
        "engine_hours_since_last_service" : getattr(asset, "engine_hours_since_last_service", 0),
        "days_since_last_service"         : getattr(asset, "days_since_last_service", 0),
        "mileage_since_last_service_km"   : getattr(asset, "mileage_since_last_service_km", 0),
        "avg_payload_kg"                  : getattr(asset, "avg_payload_kg", 0),
        "overload_events_30d"             : getattr(asset, "overload_events_30d", 0),
        "distance_last_30d_km"            : getattr(asset, "distance_last_30d_km", 0),
        "operating_hours_last_30d"        : getattr(asset, "operating_hours_last_30d", 0),
        "idle_hours_last_30d"             : getattr(asset, "idle_hours_last_30d", 0),
        "trip_count_30d"                  : getattr(asset, "trip_count_30d", 0),
        "avg_trip_distance_km"            : getattr(asset, "avg_trip_distance_km", 0),
        "start_stop_burden_30d"           : getattr(asset, "start_stop_burden_30d", 0),
        "rough_road_pct"                  : getattr(asset, "rough_road_pct", 20),
        "urban_route_pct"                 : getattr(asset, "urban_route_pct", 50),
        "port_route_pct"                  : getattr(asset, "port_route_pct", 0),
        "fuel_rate_lph"                   : getattr(asset, "fuel_rate_lph", 0),
        "fuel_efficiency_km_per_l"        : getattr(asset, "fuel_efficiency_km_per_l", 0),
        "engine_temp_avg_c"               : getattr(asset, "engine_temp_avg_c", 85),
        "coolant_temp_max_c"              : getattr(asset, "coolant_temp_max_c", 95),
        "vibration_rms_mm_s"              : getattr(asset, "vibration_rms_mm_s", 2.0),
        "tire_pressure_psi"               : getattr(asset, "tire_pressure_psi", 72),
        "battery_voltage_v"               : getattr(asset, "battery_voltage_v", 12.5),
        "ambient_temp_avg_c"              : getattr(asset, "ambient_temp_avg_c", 30),
        "ambient_humidity_avg_pct"        : getattr(asset, "ambient_humidity_avg_pct", 75),
        "rainfall_mm_30d"                 : getattr(asset, "rainfall_mm_30d", 100),
        "route_type"                      : getattr(asset, "route_type", None),
        "cargo_type"                      : getattr(asset, "cargo_type", None),
        "operating_shift"                 : getattr(asset, "operating_shift", None),
        "maintenance_priority"            : getattr(asset, "maintenance_priority", "Medium"),
        "last_service_type"               : (getattr(last_event, "service_type", None) if last_event else "oil_service"),
        "major_component_replaced"        : (getattr(last_event, "major_component_replaced", None) if last_event else "none"),
        "parts_replaced_last_service"     : (getattr(last_event, "parts_replaced", None) if last_event else ""),
        "service_provider_type"           : (getattr(last_event, "service_provider_type", None) if last_event else "in_house"),
    }


def run_batch_for_all_assets(
    db: Session,
    clf_model,
    clf_features: list,
    clf_threshold: float,
    clf_categorical_cols: list,
    reg_model,
    reg_features: list,
    reg_categorical_cols: list,
    cost_bundle: dict | None = None,
) -> None:
    """
    Run PdM + cost predictions for every active asset.

    Parameters
    ----------
    db                   SQLAlchemy session (closed by caller)
    clf_model            LgbModelBundle — failure classifier
    clf_features         list[str]
    clf_threshold        float — F1-optimal probability threshold
    clf_categorical_cols list[str]
    reg_model            LgbModelBundle — RUL regressor
    reg_features         list[str]
    reg_categorical_cols list[str]
    cost_bundle          dict | None — CatBoost v3 bundle from load_cost_bundle()
                         Pass None to skip cost predictions (safe fallback)
    """
    from app.models import (
        Asset,
        AssetCostPrediction,
        AssetFailurePrediction,
        MaintenanceEvent,
        PredictionRun,
    )
    from app.ai.services.prediction_service import (
        run_classification,
        run_health_score,
        run_regression,
    )

    # ── Create a PredictionRun record for this batch ──────────────────────────
    run = PredictionRun(
        id=str(uuid.uuid4()),
        run_started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.add(run)
    db.flush()

    assets = db.query(Asset).filter(Asset.status != "decommissioned").all()
    log.info("Batch run %s — processing %d assets", run.id, len(assets))

    success_count = 0
    fail_count    = 0

    for asset in assets:
        try:
            data = {
                "asset_id"   : str(asset.id),
                "vehicle_type": asset.vehicle_type,
                "vehicle_role": getattr(asset, "vehicle_role", None),
                # ── health fields passed to PdM models ────────────────────────
                "oil_life_pct"           : getattr(asset, "oil_life_pct", 50),
                "brake_health_pct"       : getattr(asset, "brake_health_pct", 50),
                "tire_health_pct"        : getattr(asset, "tire_health_pct", 50),
                "battery_health_pct"     : getattr(asset, "battery_health_pct", 50),
                "hydraulic_health_pct"   : getattr(asset, "hydraulic_health_pct", 50),
                "engine_hours_since_last_service": getattr(asset, "engine_hours_since_last_service", 0),
                "days_since_last_service": getattr(asset, "days_since_last_service", 0),
                "odometer_km"            : getattr(asset, "current_mileage", 0),
                "active_fault_code_count": getattr(asset, "active_fault_code_count", 0),
                "sensor_fault_flag"      : getattr(asset, "sensor_fault_flag", 0),
                "downtime_hours_last_90d": getattr(asset, "downtime_hours_last_90d", 0),
                "payload_utilization_pct": getattr(asset, "payload_utilization_pct", 50),
                "vehicle_age_years"      : getattr(asset, "vehicle_age_years", 0),
                "payload_capacity_kg"    : getattr(asset, "payload_capacity_kg", 0),
                "fuel_rate_lph"          : getattr(asset, "fuel_rate_lph", 0),
                "vibration_rms_mm_s"     : getattr(asset, "vibration_rms_mm_s", 2.0),
                "engine_temp_avg_c"      : getattr(asset, "engine_temp_avg_c", 85),
                "overload_events_30d"    : getattr(asset, "overload_events_30d", 0),
            }

            # ── Failure classification ────────────────────────────────────────
            clf_result = run_classification(data, clf_model, clf_features)

            # ── RUL regression ────────────────────────────────────────────────
            reg_result = run_regression(data, reg_model, reg_features)

            # ── Health score ──────────────────────────────────────────────────
            health_result = run_health_score(data)

            # ── Write AssetFailurePrediction ──────────────────────────────────
            db.add(AssetFailurePrediction(
                id                   = str(uuid.uuid4()),
                asset_id             = str(asset.id),
                run_id               = run.id,
                failure_probability  = clf_result.get("failure_probability", 0.0),
                risk_level           = clf_result.get("risk_level", "low"),
                health_score         = health_result.get("health_score", 0.0),
                days_until_failure   = reg_result.get("days_until_failure"),
                predicted_failure_date=reg_result.get("predicted_failure_date"),
                model_version        = "pdm-v7",
                created_at           = datetime.now(timezone.utc),
            ))

            # ── Cost estimation v3 (CatBoost) ─────────────────────────────────
            if cost_bundle is not None:
                try:
                    from app.ai.models.cost_estimation_model.cost_model import predict_cost

                    last_event = (
                        db.query(MaintenanceEvent)
                        .filter(MaintenanceEvent.asset_id == asset.id)
                        .order_by(MaintenanceEvent.service_date.desc())
                        .first()
                    )

                    cost_result = predict_cost(
                        _build_cost_input(asset, last_event),
                        cost_bundle,
                        top_k=5,
                    )

                    # Upsert — only one cost record per asset per run
                    existing = (
                        db.query(AssetCostPrediction)
                        .filter(
                            AssetCostPrediction.asset_id == str(asset.id),
                            AssetCostPrediction.run_id   == run.id,
                        )
                        .first()
                    )
                    if existing:
                        existing.estimated_cost  = cost_result["predicted_cost_lkr"]
                        existing.confidence_lower= cost_result["pi_80_lower_lkr"]
                        existing.confidence_upper= cost_result["pi_80_upper_lkr"]
                        existing.model_version   = "cost-v3.0"
                        existing.extra_data      = cost_result
                    else:
                        db.add(AssetCostPrediction(
                            id               = str(uuid.uuid4()),
                            asset_id         = str(asset.id),
                            run_id           = run.id,
                            estimated_cost   = cost_result["predicted_cost_lkr"],
                            confidence_lower = cost_result["pi_80_lower_lkr"],
                            confidence_upper = cost_result["pi_80_upper_lkr"],
                            model_version    = "cost-v3.0",
                            extra_data       = cost_result,
                            created_at       = datetime.now(timezone.utc),
                        ))

                except Exception as cost_exc:
                    log.warning(
                        "Cost v3 prediction failed for asset %s: %s",
                        asset.id, cost_exc,
                    )

            success_count += 1

        except Exception as exc:
            fail_count += 1
            log.warning("Batch prediction failed for asset %s: %s", asset.id, exc)
            continue

        # Commit in chunks to avoid holding one giant transaction
        if success_count % 50 == 0:
            db.commit()

    # ── Finalise run record ───────────────────────────────────────────────────
    run.status           = "completed"
    run.run_completed_at = datetime.now(timezone.utc)
    run.assets_processed = success_count
    run.assets_failed    = fail_count
    db.commit()

    log.info(
        "Batch run %s complete — success=%d  failed=%d  cost_model=%s",
        run.id, success_count, fail_count,
        "v3" if cost_bundle is not None else "skipped",
    )