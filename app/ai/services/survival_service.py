"""
FRSO survival service — loads the per-component Weibull AFT models and
serves predictions at request time.

Each component (brake, tire, battery, oil, hydraulic) has its own model that
answers two questions for a given asset:
    1. What's the survival curve S(t) over the next N days?
    2. What's the median predicted failure time (the p50 RUL)?

Models and feature schemas live in `app/ai/models/survival_analysis/` and are
loaded lazily on first call (kept in a module-level cache so subsequent calls
are free). The training script `app/ai/datasets/train_frso_survival.py` writes
them.

Feature extraction reuses the same Asset + SensorReading columns the
CatBoost service already pulls, then maps them onto the column names the
survival models were trained with.
"""

from __future__ import annotations

import json
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.ai.services.vehicle_prediction_service import (
    _get_asset,
    _get_latest_sensor_reading,
    _to_float,
    _to_int,
)

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "survival_analysis"
COMPONENTS = ("brake", "tire", "battery", "oil", "hydraulic")


# ── Model loading (cached) ────────────────────────────────────────────────────

@lru_cache(maxsize=len(COMPONENTS))
def _load_model(component: str):
    """Load the .pkl model for one component. Cached for process lifetime."""
    path = MODEL_DIR / f"{component}_aft.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"Survival model not found at {path}. "
            f"Run `python -m app.ai.datasets.train_frso_survival` first."
        )
    with open(path, "rb") as f:
        return pickle.load(f)


@lru_cache(maxsize=len(COMPONENTS))
def _load_feature_schema(component: str) -> dict[str, Any]:
    path = MODEL_DIR / f"{component}_features.json"
    if not path.exists():
        raise FileNotFoundError(f"Feature schema not found at {path}.")
    return json.loads(path.read_text())


def warmup_survival_models() -> None:
    """Eagerly load all per-component models. Called from app/main.py startup."""
    for c in COMPONENTS:
        _load_model(c)
        _load_feature_schema(c)


# ── Feature extraction from DB rows ───────────────────────────────────────────

def build_asset_feature_dict(db: Session, asset_id: str) -> dict[str, Any]:
    """
    Build the feature dict expected by the survival models from the asset's
    latest SensorReading + Asset metadata.

    Returns covariates in the schema the training script saw (before one-hot
    encoding). Categorical strings stay as strings — `_one_hot_align` handles
    encoding to match the model's training columns.
    """
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    reading = _get_latest_sensor_reading(db, asset_id)
    if not reading:
        raise ValueError("No sensor reading found for asset")

    age_years = _to_float(asset.vehicle_age_years, default=1.0) or 1.0
    engine_hours_total = _to_float(getattr(reading, "engine_hours_total", None))
    hours_per_day = engine_hours_total / max(1.0, age_years * 365.0)

    return {
        # numeric covariates (must match the training column names exactly)
        "vehicle_age_years":        round(age_years, 2),
        "engine_hours_total":       round(engine_hours_total, 1),
        "hours_per_day":            round(hours_per_day, 2),
        "payload_utilization_pct":  _to_float(getattr(reading, "payload_utilization_pct", None)),
        "overload_events_30d":      _to_int(getattr(reading, "overload_events_30d", None)),
        "avg_vibration_rms_mm_s":   _to_float(getattr(reading, "vibration_rms_mm_s", None)),
        "avg_engine_temp_c":        _to_float(getattr(reading, "engine_temp_avg_c", None)),
        "ambient_humidity_avg_pct": _to_float(getattr(reading, "ambient_humidity_avg_pct", None)),
        "rough_road_pct":           _to_float(getattr(reading, "rough_road_pct", None)),
        "port_route_pct":           _to_float(getattr(reading, "port_route_pct", None)),
        "days_since_last_service":  _to_int(getattr(reading, "days_since_last_service", None)),
        # categoricals (one-hot encoded at predict time to match training)
        "vehicle_type":             asset.vehicle_type or "Other",
        "vehicle_role":             asset.vehicle_role or asset.vehicle_type or "transport",
    }


def _one_hot_align(features: dict[str, Any], schema: dict[str, Any]) -> pd.DataFrame:
    """
    Convert a feature dict into a single-row DataFrame whose columns exactly
    match the model's training schema. Missing one-hot columns are filled with 0.
    """
    raw = pd.DataFrame([features])
    one_hot_cols = schema.get("categorical_one_hot", [])
    encoded = pd.get_dummies(raw, columns=one_hot_cols, drop_first=True)

    # bool columns from pd.get_dummies → int (lifelines wants numeric)
    bool_cols = encoded.select_dtypes(include="bool").columns
    encoded[bool_cols] = encoded[bool_cols].astype(int)

    expected = schema["feature_cols"]
    for col in expected:
        if col not in encoded.columns:
            encoded[col] = 0
    return encoded[expected]


# ── Public prediction API ─────────────────────────────────────────────────────

def predict_survival_curve(
    db: Session,
    asset_id: str,
    component: str,
    horizon_days: int = 180,
    step_days: int = 7,
) -> dict[str, Any]:
    """
    Predict the survival curve S(t) for one component of one asset over the
    next `horizon_days` days, sampled every `step_days` days.

    Returns:
        {
            "asset_id":     "SLW0001",
            "component":    "brake",
            "median_days":  142.3,           # p50 RUL
            "p10_days":      71.1,           # 90% chance of failing after this
            "p90_days":     245.7,           # 10% chance of failing after this
            "curve": [
                {"day":   0, "survival_prob": 1.000},
                {"day":   7, "survival_prob": 0.987},
                ...
                {"day": 180, "survival_prob": 0.422},
            ],
        }
    """
    if component not in COMPONENTS:
        raise ValueError(f"Unknown component '{component}'. Expected one of {COMPONENTS}.")

    model  = _load_model(component)
    schema = _load_feature_schema(component)

    features = build_asset_feature_dict(db, asset_id)
    x_row    = _one_hot_align(features, schema)

    times = np.arange(0, horizon_days + 1, step_days, dtype=float)
    survival = model.predict_survival_function(x_row, times=times)
    # predict_survival_function returns a DataFrame indexed by time, columns = rows
    s_curve = survival.iloc[:, 0].values

    p10 = float(model.predict_percentile(x_row, p=0.10).iloc[0])
    p50 = float(model.predict_percentile(x_row, p=0.50).iloc[0])
    p90 = float(model.predict_percentile(x_row, p=0.90).iloc[0])

    return {
        "asset_id":   asset_id,
        "component":  component,
        "median_days": round(p50, 2),
        "p10_days":    round(p10, 2),
        "p90_days":    round(p90, 2),
        "curve": [
            {"day": int(t), "survival_prob": round(float(s), 4)}
            for t, s in zip(times, s_curve)
        ],
    }


def predict_all_components(
    db: Session,
    asset_id: str,
    horizon_days: int = 180,
    step_days: int = 14,
) -> dict[str, Any]:
    """
    Predict survival curves for all 5 components of one asset in a single call.

    Useful for the asset-detail screen ("show me the RUL for every part") and
    as the input source for the scheduling optimiser ("which assets are most
    at risk in the next 2 weeks?").
    """
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    components_out: list[dict[str, Any]] = []
    soonest_median = float("inf")
    soonest_component: str | None = None

    for c in COMPONENTS:
        try:
            result = predict_survival_curve(db, asset_id, c, horizon_days, step_days)
        except Exception as e:
            components_out.append({"component": c, "error": str(e)})
            continue

        components_out.append(result)
        if result["median_days"] < soonest_median:
            soonest_median   = result["median_days"]
            soonest_component = c

    return {
        "asset_id":           asset_id,
        "horizon_days":       horizon_days,
        "step_days":          step_days,
        "soonest_component":  soonest_component,
        "soonest_median_days": round(soonest_median, 2) if soonest_component else None,
        "components":         components_out,
    }


def fleet_survival_summary(
    db: Session,
    max_assets: int = 12,
    horizon_days: int = 180,
    asset_codes: list[str] | None = None,
) -> dict[str, Any]:
    """
    Fleet-level survival aggregation over the warehouse's most at-risk assets.

    When `asset_codes` is given, those exact assets are scored (used by the
    warehouse report so the §4.8 page matches its critical-asset list). Otherwise
    the `max_assets` lowest-health assets (by latest failure-prediction health
    score) are picked. For each asset all 5 component models are run and
    aggregated into:
      - component_summary: per-component avg median RUL + at-risk (≤30d / ≤90d) counts
      - watchlist:         each asset's soonest-failing component, sorted by RUL

    Drives both the warehouse report's §4.8 page and the
    GET /survival/warehouse/summary endpoint.
    """
    from app.models import Asset, AssetFailurePrediction

    if asset_codes:
        rows = (
            db.query(Asset.asset_code, Asset.id)
            .filter(Asset.asset_code.in_(asset_codes[:max_assets]))
            .all()
        )
    else:
        rows = (
            db.query(Asset.asset_code, Asset.id)
            .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id)
            .filter(AssetFailurePrediction.health_score.isnot(None))
            .order_by(AssetFailurePrediction.health_score.asc())
            .limit(max_assets)
            .all()
        )

    comp_rul: dict[str, list] = {c: [] for c in COMPONENTS}
    comp_30 = {c: 0 for c in COMPONENTS}
    comp_90 = {c: 0 for c in COMPONENTS}
    watchlist: list = []
    analyzed = 0

    for code, aid in rows:
        try:
            res = predict_all_components(db, str(aid), horizon_days=horizon_days, step_days=14)
        except Exception:
            continue
        analyzed += 1
        for comp in res.get("components", []):
            if "error" in comp:
                continue
            c, md = comp["component"], comp["median_days"]
            comp_rul[c].append(md)
            if md <= 30:
                comp_30[c] += 1
            if md <= 90:
                comp_90[c] += 1
        sc, sm = res.get("soonest_component"), res.get("soonest_median_days")
        if sc and sm is not None:
            watchlist.append({
                "asset": code,
                "component": sc.title(),
                "rul_days": round(float(sm), 1),
                "risk": "High" if sm <= 45 else "Medium" if sm <= 90 else "Low",
            })

    component_summary = [
        {
            "component": c.title(),
            "avg_rul_days": round(sum(v) / len(v), 1) if v else None,
            "at_risk_30d": comp_30[c],
            "at_risk_90d": comp_90[c],
            "assets_scored": len(v),
        }
        for c, v in comp_rul.items()
    ]
    watchlist.sort(key=lambda w: w["rul_days"])

    return {
        "assets_analyzed": analyzed,
        "horizon_days": horizon_days,
        "component_summary": component_summary,
        "watchlist": watchlist[:15],
    }
