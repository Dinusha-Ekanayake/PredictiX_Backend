"""
FRSO survival service (v3) — per-component Weibull AFT on the real v11 schema.

Five models (brake, tire, battery, oil, hydraulic) each read ONE latest asset
snapshot and return a survival curve S(t), the median remaining life, a p10-p90
band, and — new in v3 — the probability of failing within 7 and 30 days.

Design (mirrors the training pipeline in
`app/ai/models/survival_analysis/train_survival_models.py`):
  * target learned from the real dataset: duration = days_until_next_maintenance,
    event = (next_service_type == that component's service).
  * features are the real snapshot columns; numeric features are z-scored with a
    scaler stored in each `{component}_features.json`, so inference must apply the
    SAME transform (see `_design_row`).
  * servicing just resets `days_since_last_service` — no degradation history is
    needed, which is why a single snapshot is enough.

Warehouse reporting (`fleet_survival_summary`) fuses three models, each owning
its question:
    PdM   (asset_failure_predictions) -> WHICH assets are critical
    this  (survival)                  -> WHICH component, P(fail) in 7 / 30 days
    cost  (asset_cost_predictions)    -> WHAT the replacement costs
and returns the expected replacement spend for the next 7 and 30 days.
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.services.vehicle_prediction_service import (
    _get_asset,
    _get_latest_sensor_reading,
    _to_float,
    _to_int,
)

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "survival_analysis"
COMPONENTS = ("brake", "tire", "battery", "oil", "hydraulic")
HORIZONS = (7, 30)

COMPONENT_HEALTH_COL = {
    "brake":     "brake_health_pct",
    "tire":      "tire_health_pct",
    "battery":   "battery_health_pct",
    "oil":       "oil_life_pct",
    "hydraulic": "hydraulic_health_pct",
}

# Static covariates that live on the Asset row.
_ASSET_STATIC = [
    "vehicle_age_years", "payload_capacity_kg",
    "lifetime_service_count", "lifetime_breakdown_count",
]
# Dynamic covariates that live on the latest SensorReading.
_SENSOR_NUMERIC = [
    "odometer_km", "engine_hours_total", "vibration_rms_mm_s",
    "engine_hours_since_last_service", "days_since_last_service",
    "mileage_since_last_service_km", "active_fault_code_count", "sensor_fault_flag",
    "payload_utilization_pct", "overload_events_30d", "downtime_hours_last_90d",
    "start_stop_burden_30d", "engine_temp_avg_c", "coolant_temp_max_c",
    "ambient_temp_avg_c", "ambient_humidity_avg_pct", "rainfall_mm_30d",
    "rough_road_pct", "urban_route_pct", "port_route_pct",
]
_HEALTH_COLS = list(COMPONENT_HEALTH_COL.values())

# Survival-probability levels behind the reported percentiles:
#   p10_days -> earliest, "90% sure it still works past this day" -> S(t)=0.90
#   median  -> S(t)=0.50 ;  p90_days -> latest, S(t)=0.10
_PCTL = {"p10_days": 0.90, "median_days": 0.50, "p90_days": 0.10}


# ── Model + schema loading (cached) ───────────────────────────────────────────

@lru_cache(maxsize=len(COMPONENTS))
def _load_model(component: str):
    path = MODEL_DIR / f"{component}_aft.pkl"
    if not path.exists():
        raise FileNotFoundError(
            f"Survival model not found at {path}. Train + deploy the v3 models "
            f"(app/ai/models/survival_analysis/train_survival_models.py)."
        )
    with open(path, "rb") as f:
        return pickle.load(f)


@lru_cache(maxsize=len(COMPONENTS))
def _load_schema(component: str) -> dict[str, Any]:
    path = MODEL_DIR / f"{component}_features.json"
    if not path.exists():
        raise FileNotFoundError(f"Feature schema not found at {path}.")
    return json.loads(path.read_text())


def warmup_survival_models() -> None:
    """Eagerly load all five models + schemas (call from app startup)."""
    for c in COMPONENTS:
        _load_model(c)
        _load_schema(c)


# ── Feature extraction from DB rows ───────────────────────────────────────────

@lru_cache(maxsize=1)
def _v11_snapshots() -> dict[str, Any]:
    """Canonical v11 snapshot per asset_code — the dataset the PdM + cost models
    were built on.

    Used as the survival feature source so the report stays coherent with the
    PdM criticality: in the demo environment the live `sensor_readings` table can
    drift out of sync with v11 (e.g. refreshed to healthy values while the stored
    PdM predictions still reflect the degraded v11 state). Scoring the same v11
    snapshot the rest of the pipeline uses keeps "critical asset → at-risk
    component" consistent. Falls back to the live reading when an asset is absent.
    """
    path = MODEL_DIR / "v11_snapshots.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_asset_feature_dict(db: Session, asset_id: str) -> dict[str, Any]:
    """Raw covariate dict (pre-transform) for one asset.

    Prefers the canonical v11 snapshot (keyed by asset_code); otherwise builds
    from the asset's latest SensorReading. Values may be Decimal/None/bool —
    `_design_row` coerces them and fills any missing numeric with the training
    mean, so a missing field stays neutral instead of collapsing to zero.
    """
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    snap = _v11_snapshots().get(getattr(asset, "asset_code", None) or "")
    if snap:
        feat = dict(snap)
        feat.setdefault("vehicle_type", asset.vehicle_type or "__missing__")
        feat.setdefault("vehicle_role", getattr(asset, "vehicle_role", None) or "__missing__")
        return feat

    reading = _get_latest_sensor_reading(db, asset_id)
    if not reading:
        raise ValueError("No sensor reading found for asset")

    feat: dict[str, Any] = {}
    for col in _ASSET_STATIC:
        feat[col] = getattr(asset, col, None)
    # vehicle_age fallback from manufacture_year if not stored on the asset
    if feat.get("vehicle_age_years") in (None, 0):
        my = getattr(asset, "manufacture_year", None)
        if my:
            feat["vehicle_age_years"] = max(0, datetime.utcnow().year - int(my))
    for col in _SENSOR_NUMERIC + _HEALTH_COLS:
        feat[col] = getattr(reading, col, None)
    feat["vehicle_type"] = asset.vehicle_type or "__missing__"
    feat["vehicle_role"] = getattr(asset, "vehicle_role", None) or "__missing__"
    return feat


def _design_row(feat: dict[str, Any], schema: dict[str, Any]) -> pd.DataFrame:
    """Single-row design matrix matching training (z-score + one-hot + reindex)."""
    cols = schema["numeric_cols"] + schema["categorical_cols"]
    df = pd.DataFrame([{c: feat.get(c) for c in cols}])
    for col, (mean, std) in schema["scaler"].items():
        vals = pd.to_numeric(df.get(col), errors="coerce").fillna(mean)
        df[col] = (vals - mean) / (std if std else 1.0)
    for col in schema["categorical_cols"]:
        df[col] = df[col].astype(str).fillna("__missing__")
    df = pd.get_dummies(df, columns=schema["categorical_cols"], drop_first=True)
    bool_cols = df.select_dtypes(include="bool").columns
    df[bool_cols] = df[bool_cols].astype(int)
    for col in schema["feature_cols"]:
        if col not in df.columns:
            df[col] = 0
    return df[schema["feature_cols"]]


# ── Core per-component scoring ────────────────────────────────────────────────

def _score_component(feat: dict[str, Any], component: str,
                     times: np.ndarray | None = None) -> dict[str, Any]:
    model = _load_model(component)
    schema = _load_schema(component)
    X = _design_row(feat, schema)

    horizon = np.array(HORIZONS, dtype=float)
    sf_h = model.predict_survival_function(X, times=horizon).iloc[:, 0].values
    surv = {int(h): float(np.clip(sf_h[i], 0, 1)) for i, h in enumerate(HORIZONS)}

    pct = {}
    for name, p in _PCTL.items():
        try:
            pct[name] = round(float(model.predict_percentile(X, p=p).iloc[0]), 2)
        except Exception:
            pct[name] = float("nan")

    health = feat.get(schema["health_col"])
    out = {
        "component":     component,
        "health_pct":    _to_float(health) if health is not None else None,
        "survival_7d":   surv[7],
        "survival_30d":  surv[30],
        "fail_prob_7d":  round(1.0 - surv[7], 4),
        "fail_prob_30d": round(1.0 - surv[30], 4),
        "median_days":   pct["median_days"],
        "p10_days":      pct["p10_days"],
        "p90_days":      pct["p90_days"],
    }
    if times is not None:
        curve = model.predict_survival_function(X, times=times).iloc[:, 0].values
        out["curve"] = [
            {"day": int(t), "survival_prob": round(float(s), 4)}
            for t, s in zip(times, curve)
        ]
    return out


# ── Public: single-component curve (asset endpoint — backward compatible) ─────

def predict_survival_curve(db: Session, asset_id: str, component: str,
                           horizon_days: int = 180, step_days: int = 7) -> dict[str, Any]:
    if component not in COMPONENTS:
        raise ValueError(f"Unknown component '{component}'. Expected one of {COMPONENTS}.")
    feat = build_asset_feature_dict(db, asset_id)
    times = np.arange(0, horizon_days + 1, step_days, dtype=float)
    scored = _score_component(feat, component, times=times)
    scored["asset_id"] = asset_id
    return scored


# ── Public: all five components for one asset (asset endpoint — backward compat) ─

def predict_all_components(db: Session, asset_id: str,
                           horizon_days: int = 180, step_days: int = 14) -> dict[str, Any]:
    asset = _get_asset(db, asset_id)
    if not asset:
        raise ValueError("Asset not found")

    feat = build_asset_feature_dict(db, asset_id)
    times = np.arange(0, horizon_days + 1, step_days, dtype=float)

    components_out: list[dict[str, Any]] = []
    soonest_median = float("inf")
    soonest_component: str | None = None
    for c in COMPONENTS:
        try:
            res = _score_component(feat, c, times=times)
            res["asset_id"] = asset_id
        except Exception as e:
            components_out.append({"component": c, "error": str(e)})
            continue
        components_out.append(res)
        md = res["median_days"]
        if md == md and md < soonest_median:   # md == md filters NaN
            soonest_median, soonest_component = md, c

    return {
        "asset_id":            asset_id,
        "horizon_days":        horizon_days,
        "step_days":           step_days,
        "soonest_component":   soonest_component,
        "soonest_median_days": round(soonest_median, 2) if soonest_component else None,
        "components":          components_out,
    }


# ── Warehouse fleet summary (the warehouse report — new in v3) ────────────────

def _p_service(fail_probs: list[float]) -> float:
    """P(at least one of the five components fails within the horizon)."""
    return float(1.0 - np.prod([1.0 - p for p in fail_probs]))


def _latest_cost_map(db: Session, codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}
    rows = db.execute(text("""
        SELECT a.asset_code, c.estimated_cost
        FROM (
            SELECT DISTINCT ON (asset_id) asset_id, estimated_cost, created_at
            FROM asset_cost_predictions
            ORDER BY asset_id, created_at DESC
        ) c
        JOIN assets a ON a.id = c.asset_id
        WHERE a.asset_code = ANY(:codes)
    """), {"codes": codes}).fetchall()
    return {r[0]: (float(r[1]) if r[1] is not None else None) for r in rows}


def fleet_survival_summary(db: Session, max_assets: int = 12,
                           horizon_days: int = 180,
                           asset_codes: list[str] | None = None) -> dict[str, Any]:
    """Warehouse-level survival + cost aggregation over the critical set.

    * Critical set comes from the PdM pipeline (asset_failure_predictions) — either
      the explicit `asset_codes` or the `max_assets` lowest-health assets.
    * Each asset is scored on all five components for P(fail) in 7 / 30 days.
    * Replacement cost is read from the cost model (asset_cost_predictions), and
      the expected spend is  P(service within Nd) * cost  summed over the fleet.

    Returns the new warehouse-report structure PLUS the legacy `component_summary`
    / `watchlist` keys so existing consumers keep working.
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

    codes = [r[0] for r in rows]
    cost_map = _latest_cost_map(db, codes)

    comp_rul: dict[str, list] = {c: [] for c in COMPONENTS}
    comp_p7: dict[str, list] = {c: [] for c in COMPONENTS}
    comp_p30: dict[str, list] = {c: [] for c in COMPONENTS}
    at_risk_7 = {c: 0 for c in COMPONENTS}
    at_risk_30 = {c: 0 for c in COMPONENTS}
    assets_out: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []
    exp_spend_7 = exp_spend_30 = 0.0
    analyzed = 0

    for code, aid in rows:
        try:
            feat = build_asset_feature_dict(db, str(aid))
            comps = {c: _score_component(feat, c) for c in COMPONENTS}
        except Exception:
            continue
        analyzed += 1

        f7 = [comps[c]["fail_prob_7d"] for c in COMPONENTS]
        f30 = [comps[c]["fail_prob_30d"] for c in COMPONENTS]
        ps7, ps30 = _p_service(f7), _p_service(f30)
        cost = cost_map.get(code)
        e7 = ps7 * cost if cost is not None else None
        e30 = ps30 * cost if cost is not None else None
        if e7:
            exp_spend_7 += e7
        if e30:
            exp_spend_30 += e30

        soonest = min(comps.values(),
                      key=lambda d: (np.inf if d["median_days"] != d["median_days"] else d["median_days"]))
        for c in COMPONENTS:
            md = comps[c]["median_days"]
            if md == md:
                comp_rul[c].append(md)
            comp_p7[c].append(comps[c]["fail_prob_7d"])
            comp_p30[c].append(comps[c]["fail_prob_30d"])
            if comps[c]["fail_prob_7d"] >= 0.20:
                at_risk_7[c] += 1
            if comps[c]["fail_prob_30d"] >= 0.20:
                at_risk_30[c] += 1

        assets_out.append({
            "asset":              code,
            "components":         {c: {"fail_prob_7d": comps[c]["fail_prob_7d"],
                                       "fail_prob_30d": comps[c]["fail_prob_30d"],
                                       "median_days": comps[c]["median_days"],
                                       "health_pct": comps[c]["health_pct"]}
                                  for c in COMPONENTS},
            "soonest_component":  soonest["component"],
            "soonest_median_days": soonest["median_days"],
            "p_service_7d":       round(ps7, 4),
            "p_service_30d":      round(ps30, 4),
            "est_cost_lkr":       cost,
            "exp_cost_7d_lkr":    round(e7, 2) if e7 is not None else None,
            "exp_cost_30d_lkr":   round(e30, 2) if e30 is not None else None,
        })
        watchlist.append({
            "asset":     code,
            "component": soonest["component"].title(),
            "rul_days":  round(float(soonest["median_days"]), 1) if soonest["median_days"] == soonest["median_days"] else None,
            "risk":      "High" if ps30 >= 0.5 else "Medium" if ps30 >= 0.2 else "Low",
        })

    component_summary = [
        {
            "component":     c.title(),
            "avg_rul_days":  round(sum(v) / len(v), 1) if v else None,
            # average failure probability across the scored assets (drives the bar chart)
            "avg_fail_prob_7d":  round(sum(comp_p7[c]) / len(comp_p7[c]), 4) if comp_p7[c] else 0.0,
            "avg_fail_prob_30d": round(sum(comp_p30[c]) / len(comp_p30[c]), 4) if comp_p30[c] else 0.0,
            # expected number of failures = sum of per-asset probabilities
            "expected_failures_7d":  round(sum(comp_p7[c]), 2),
            "expected_failures_30d": round(sum(comp_p30[c]), 2),
            "at_risk_7d":    at_risk_7[c],
            "at_risk_30d":   at_risk_30[c],
            "assets_scored": len(v),
        }
        for c, v in comp_rul.items()
    ]
    watchlist.sort(key=lambda w: (w["rul_days"] is None, w["rul_days"]))

    return {
        "assets_analyzed":     analyzed,
        "horizon_days":        horizon_days,
        "currency":            "LKR",
        "expected_spend_7d":   round(exp_spend_7, 2),
        "expected_spend_30d":  round(exp_spend_30, 2),
        "component_summary":   component_summary,
        "assets":              assets_out,      # per-asset 5-component 7/30d + cost
        "watchlist":           watchlist[:15],
        "generated_at":        datetime.utcnow().isoformat() + "Z",
    }
