from datetime import timedelta

import numpy as np
import pandas as pd
from catboost import Pool
from fastapi import HTTPException


REGRESSION_CATEGORICAL_FEATURES = ["vehicle_role"]


def prepare_input(data: dict, feature_list: list[str]) -> pd.DataFrame:
    df = pd.DataFrame([data])

    for col in feature_list:
        if col not in df.columns:
            if col in REGRESSION_CATEGORICAL_FEATURES:
                df[col] = "unknown"
            else:
                df[col] = 0

    return df.loc[:, feature_list].copy()


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


def clean_and_cast_inputs(df: pd.DataFrame, categorical_features: list[str]) -> pd.DataFrame:
    cleaned = df.copy()

    for col in cleaned.columns:
        if col in categorical_features:
            cleaned[col] = cleaned[col].astype(str)
        else:
            try:
                cleaned[col] = pd.to_numeric(cleaned[col], errors="raise")
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail=f"Field '{col}' must be numeric",
                )

    return cleaned


def get_risk_and_action(prob: float, pred_days: int | None = None) -> tuple[str, str]:
    if pred_days is not None:
        if prob >= 0.8 or pred_days <= 7:
            return "High", "Schedule maintenance immediately"
        if prob >= 0.5 or pred_days <= 30:
            return "Medium", "Inspect vehicle soon"
        return "Low", "Continue monitoring"

    if prob >= 0.8:
        return "High", "Schedule maintenance immediately"
    if prob >= 0.5:
        return "Medium", "Inspect vehicle soon"
    return "Low", "Continue monitoring"


def get_top_catboost_shap(reg_model, x_reg: pd.DataFrame) -> list[dict]:
    cat_feature_indices = [
        x_reg.columns.get_loc(col)
        for col in REGRESSION_CATEGORICAL_FEATURES
        if col in x_reg.columns
    ]

    pool = Pool(x_reg, cat_features=cat_feature_indices)
    shap_values = reg_model.get_feature_importance(type="ShapValues", data=pool)

    row_shap = shap_values[0][:-1]
    feature_names = list(x_reg.columns)

    ranked = sorted(
        zip(feature_names, row_shap),
        key=lambda x: abs(x[1]),
        reverse=True,
    )

    return [
        {"feature": feature, "impact": round(float(impact), 4)}
        for feature, impact in ranked[:5]
    ]


def _parse_snapshot_date(snapshot_date_raw: str) -> pd.Timestamp:
    try:
        return pd.to_datetime(snapshot_date_raw)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid snapshot_date format. Use YYYY-MM-DD",
        )


def run_classification(
    data: dict,
    clf_model,
    clf_features: list[str],
    clf_threshold: float = 0.5,
    clf_categorical_cols: list[str] | None = None,
) -> dict:
    if not isinstance(clf_features, list):
        raise HTTPException(status_code=500, detail="clf_features is not a list")

    required_fields = ["snapshot_date"] + clf_features
    validate_payload_fields(data, required_fields)
    _parse_snapshot_date(data["snapshot_date"])

    try:
        x_clf = prepare_input(data, clf_features)

        # XGBoost needs numeric-only input — one-hot encode categoricals
        cat_cols = [c for c in (clf_categorical_cols or []) if c in x_clf.columns]
        if cat_cols:
            x_clf = pd.get_dummies(x_clf, columns=cat_cols)
        else:
            x_clf = clean_and_cast_inputs(x_clf, categorical_features=[])

        prob = float(clf_model.predict_proba(x_clf)[0][1])
        maintenance_required = int(prob >= clf_threshold)
        risk_level, recommended_action = get_risk_and_action(prob)

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
    if not isinstance(reg_features, list):
        raise HTTPException(status_code=500, detail="reg_features is not a list")

    required_fields = ["snapshot_date"] + reg_features
    validate_payload_fields(data, required_fields)

    snapshot_date = _parse_snapshot_date(data["snapshot_date"])

    try:
        x_reg = prepare_input(data, reg_features)
        x_reg = clean_and_cast_inputs(
            x_reg,
            categorical_features=REGRESSION_CATEGORICAL_FEATURES,
        )

        reg_cat_feature_indices = [
            x_reg.columns.get_loc(col)
            for col in REGRESSION_CATEGORICAL_FEATURES
            if col in x_reg.columns
        ]
        reg_pool = Pool(x_reg, cat_features=reg_cat_feature_indices)

        pred_days = float(reg_model.predict(reg_pool)[0])
        pred_days = int(np.clip(round(pred_days), 1, 180))
        predicted_date = snapshot_date + timedelta(days=pred_days)

        top_explanations = get_top_catboost_shap(reg_model, x_reg)

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
    clf_threshold: float = 0.5,
    clf_categorical_cols: list[str] | None = None,
) -> dict:
    classification = run_classification(data, clf_model, clf_features, clf_threshold, clf_categorical_cols)
    regression = run_regression(data, reg_model, reg_features)
    health = run_health_score(data)

    risk_level, recommended_action = get_risk_and_action(
        classification["maintenance_probability"],
        regression["predicted_days_until_maintenance"],
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