from datetime import timedelta

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.ai.services.pdm_decision_service import classifier_only_tier

_TIER_TO_RISK_LABEL = {"urgent": "High", "watch": "Medium", "healthy": "Low"}
_RISK_LABEL_TO_ACTION = {
    "High": "Schedule maintenance immediately",
    "Medium": "Inspect vehicle soon",
    "Low": "Continue monitoring",
}


def validate_payload_fields(data: dict, required_fields: list[str]) -> None:
    missing_fields = [field for field in required_fields if field not in data]

    if missing_fields:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Missing required fields",
                "missing_fields": missing_fields,
                "required_fields": required_fields,
            },
        )


def get_risk_and_action(prob: float, clf_threshold: float) -> tuple[str, str]:
    """Classifier-probability-only risk estimate for the debug prediction
    endpoints, using the exact same tier boundaries the real batch
    pipeline's decision layer (pdm_decision_service) does.

    Previously used its own disconnected, hardcoded 0.8/0.5 probability
    cuts (with a 7/30-day override build_decision's tier never considers
    at all) — a probability that read e.g. "High" here could read
    "medium" risk_level in the real pdm_batch_predictions row for the
    same evidence. days_until is intentionally not used for
    classification here, matching build_decision (it only affects how
    the predicted date is framed for display, never the risk tier).
    """
    tier = classifier_only_tier(prob, clf_threshold)
    label = _TIER_TO_RISK_LABEL[tier]
    return label, _RISK_LABEL_TO_ACTION[label]


def _parse_snapshot_date(snapshot_date_raw: str) -> pd.Timestamp:
    try:
        return pd.to_datetime(snapshot_date_raw)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid snapshot_date format. Use YYYY-MM-DD",
        )


def run_classification(data: dict, clf_model, clf_features: list[str], clf_threshold: float) -> dict:
    """``clf_model`` is an app.ai.services.lgb_model_adapter.LgbModelBundle."""
    validate_payload_fields(data, ["snapshot_date"])
    snapshot_date = _parse_snapshot_date(data["snapshot_date"])

    try:
        row = {**data, "month": snapshot_date.month, "year": snapshot_date.year}
        df = clf_model.build_frame([row])
        prob = float(clf_model.predict_proba_positive(df)[0])
        maintenance_required = int(prob >= 0.6)
        risk_level, recommended_action = get_risk_and_action(prob, clf_threshold)

        return {
            "maintenance_probability": round(prob, 4),
            "maintenance_required_next_30d": maintenance_required,
            "risk_level": risk_level,
            "recommended_action": recommended_action,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Classification failed: {str(e)}")


def run_regression(data: dict, reg_model, reg_features: list[str]) -> dict:
    """``reg_model`` is an app.ai.services.lgb_model_adapter.LgbModelBundle."""
    validate_payload_fields(data, ["snapshot_date"])
    snapshot_date = _parse_snapshot_date(data["snapshot_date"])

    try:
        row = {**data, "month": snapshot_date.month, "year": snapshot_date.year}
        df = reg_model.build_frame([row])

        raw_days = float(reg_model.predict(df)[0])
        pred_days = int(np.clip(round(raw_days), 1, 365))
        predicted_date = snapshot_date + timedelta(days=pred_days)

        top_explanations = reg_model.shap_top_factors(df, top_n=5)[0]

        return {
            "predicted_days_until_maintenance": pred_days,
            "predicted_maintenance_date": str(predicted_date.date()),
            "top_explanations": top_explanations,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Regression failed: {str(e)}")


def run_health_score(data: dict) -> dict:
    required_fields = [
        "tire_health_pct",
        "brake_health_pct",
        "battery_health_pct",
        "oil_life_pct",
        "hydraulic_health_pct",
        "engine_temp_avg_c",
        "coolant_temp_max_c",
        "vibration_rms_mm_s",
        "active_fault_code_count",
        "days_since_last_service",
        "mileage_since_last_service_km",
        "overload_events_30d",
        "downtime_hours_last_90d",
    ]
    validate_payload_fields(data, required_fields)

    try:
        tire_health = float(data["tire_health_pct"])
        brake_health = float(data["brake_health_pct"])
        battery_health = float(data["battery_health_pct"])
        oil_life = float(data["oil_life_pct"])
        hydraulic_health = float(data["hydraulic_health_pct"])

        engine_temp = float(data["engine_temp_avg_c"])
        coolant_temp = float(data["coolant_temp_max_c"])
        vibration = float(data["vibration_rms_mm_s"])
        fault_codes = float(data["active_fault_code_count"])
        days_since_service = float(data["days_since_last_service"])
        mileage_since_service = float(data["mileage_since_last_service_km"])
        overload_events = float(data["overload_events_30d"])
        downtime_hours = float(data["downtime_hours_last_90d"])

        contributions = []

        brake_contrib = brake_health * 0.22
        tire_contrib = tire_health * 0.18
        oil_contrib = oil_life * 0.18
        battery_contrib = battery_health * 0.15
        hydraulic_contrib = hydraulic_health * 0.12

        base_score = (
            brake_contrib
            + tire_contrib
            + oil_contrib
            + battery_contrib
            + hydraulic_contrib
        )

        contributions.extend([
            {"feature": "brake_health_pct", "impact": round(brake_contrib, 4)},
            {"feature": "tire_health_pct", "impact": round(tire_contrib, 4)},
            {"feature": "oil_life_pct", "impact": round(oil_contrib, 4)},
            {"feature": "battery_health_pct", "impact": round(battery_contrib, 4)},
            {"feature": "hydraulic_health_pct", "impact": round(hydraulic_contrib, 4)},
        ])

        penalties = []

        if engine_temp > 95:
            penalty = min((engine_temp - 95) * 0.8, 10)
            penalties.append({"feature": "engine_temp_avg_c", "impact": -round(penalty, 4)})

        if coolant_temp > 105:
            penalty = min((coolant_temp - 105) * 1.0, 10)
            penalties.append({"feature": "coolant_temp_max_c", "impact": -round(penalty, 4)})

        if vibration > 4.5:
            penalty = min((vibration - 4.5) * 3.5, 15)
            penalties.append({"feature": "vibration_rms_mm_s", "impact": -round(penalty, 4)})

        if fault_codes > 0:
            penalty = min(fault_codes * 2.5, 12)
            penalties.append({"feature": "active_fault_code_count", "impact": -round(penalty, 4)})

        if days_since_service > 60:
            penalty = min((days_since_service - 60) * 0.08, 10)
            penalties.append({"feature": "days_since_last_service", "impact": -round(penalty, 4)})

        if mileage_since_service > 3000:
            penalty = min((mileage_since_service - 3000) / 500, 10)
            penalties.append({"feature": "mileage_since_last_service_km", "impact": -round(penalty, 4)})

        if overload_events > 0:
            penalty = min(overload_events * 1.8, 8)
            penalties.append({"feature": "overload_events_30d", "impact": -round(penalty, 4)})

        if downtime_hours > 0:
            penalty = min(downtime_hours * 0.5, 8)
            penalties.append({"feature": "downtime_hours_last_90d", "impact": -round(penalty, 4)})

        total_penalty = sum(abs(item["impact"]) for item in penalties)

        health_score = float(np.clip(round(base_score - total_penalty, 2), 0, 100))

        if health_score >= 80:
            health_status = "Healthy"
        elif health_score >= 60:
            health_status = "Moderate"
        elif health_score >= 40:
            health_status = "Poor"
        else:
            health_status = "Critical"

        all_factors = contributions + penalties
        top_factors = sorted(all_factors, key=lambda x: abs(x["impact"]), reverse=True)[:8]

        return {
            "health_score": health_score,
            "health_status": health_status,
            "contributing_factors": top_factors,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health score calculation failed: {str(e)}")


def run_full_prediction(
    data: dict,
    clf_model,
    clf_features: list[str],
    reg_model,
    reg_features: list[str],
    clf_threshold: float,
) -> dict:
    classification = run_classification(data, clf_model, clf_features, clf_threshold)
    regression = run_regression(data, reg_model, reg_features)
    health = run_health_score(data)

    risk_level, recommended_action = get_risk_and_action(
        classification["maintenance_probability"],
        clf_threshold,
    )

    return {
        "maintenance_probability": classification["maintenance_probability"],
        "maintenance_required_next_30d": classification["maintenance_required_next_30d"],
        "predicted_days_until_maintenance": regression["predicted_days_until_maintenance"],
        "predicted_maintenance_date": regression["predicted_maintenance_date"],
        "risk_level": risk_level,
        "recommended_action": recommended_action,
        "health_score": health["health_score"],
        "health_status": health["health_status"],
        "top_explanations": regression["top_explanations"],
        "contributing_factors": health["contributing_factors"],
    }
