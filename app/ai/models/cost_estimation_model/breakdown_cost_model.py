"""
PredictiX Breakdown Cost Estimation Model — v5.0
app/ai/models/cost_estimation_model/breakdown_cost_model.py

Target: maintenance_cost_lkr_next_30d
Trained on rows where maintenance_required_next_30d == 1

predict_breakdown_cost()'s signature and return dict are UNCHANGED from v4 — every
caller (predictions.py router, batch_prediction_service.py) needs no changes.
The fuel-price rescaling and svc_cost_te lookup happen entirely inside this
function and are invisible to callers.
"""
from __future__ import annotations
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from catboost import Pool

log = logging.getLogger("predictix")

MODEL_PATH = Path(__file__).resolve().parent / "predictix_breakdown_cost_model_v5.pkl"

import numba.core.serialize
_orig_unpickle = numba.core.serialize._unpickle__CustomPickled
def _safe_unpickle(*args, **kwargs):
    try:
        return _orig_unpickle(*args, **kwargs)
    except Exception:
        class DummyCtor:
            @staticmethod
            def _rebuild(**kwargs):
                return None
        class DummyPickled:
            ctor = DummyCtor
            states = {}
        return DummyPickled()
numba.core.serialize._unpickle__CustomPickled = _safe_unpickle


def load_breakdown_bundle(path: Path | str | None = None) -> dict:
    """Load the breakdown cost bundle. Call once in lifespan."""
    p = Path(path) if path else MODEL_PATH
    bundle = joblib.load(p)
    # gbm_dtypes_safe stores plain lists — rebuild CategoricalDtype at load time
    bundle["gbm_dtypes"] = {
        col: pd.CategoricalDtype(categories=cats, ordered=False)
        for col, cats in bundle.get("gbm_dtypes_safe", {}).items()
    }
    log.info(
        "Breakdown cost model loaded — version=%s predictor=%s features=%d "
        "test_R2=%.3f PICP=%.1f%% fuel_price_normalized=%s",
        bundle.get("version", "?"),
        bundle.get("predictor_name", "?"),
        len(bundle.get("feature_cols", [])),
        bundle.get("test_metrics", {}).get("R2", 0.0),
        bundle.get("picp_80_test", 0) * 100,
        bundle.get("fuel_price_normalized", False),
    )
    return bundle


def _engineer(raw: dict, bundle: dict) -> dict:
    """Feature engineering — must match training pipeline exactly.

    v5 adds `svc_cost_te` at the end: a target-encoded lookup for
    `service_vehicle`, computed leakage-safely at training time and stored in
    bundle['svc_te_map']. This must be computed AFTER `service_vehicle` itself
    is derived, since it's keyed on that combined string.
    """
    d = dict(raw)
    age  = float(d.get("vehicle_age_years", 0))
    vt   = str(d.get("vehicle_type", ""))
    # next_service_type drives service_vehicle; fall back to last_service_type
    nsv  = str(d.get("next_service_type") or d.get("last_service_type") or "oil_service")
    VSMAP = bundle["vehicle_size_map"]

    d["vehicle_size_ord"]   = VSMAP.get(vt, 3)
    d["age_band"]           = "new" if age<=3 else "mid" if age<=6 else "old" if age<=10 else "aged"
    d["service_vehicle"]    = f"{nsv}__{vt}"
    d["payload_age"]        = float(d.get("payload_capacity_kg", 0)) * age
    d["utilisation_stress"] = (float(d.get("payload_utilization_pct", 0)) *
                               float(d.get("downtime_hours_last_90d", 0)))
    d["health_index"]       = (float(d.get("oil_life_pct",       50)) +
                               float(d.get("brake_health_pct",   50)) +
                               float(d.get("tire_health_pct",    50)) +
                               float(d.get("battery_health_pct", 50))) / 4
    d["fault_stress"]       = (float(d.get("active_fault_code_count", 0)) +
                               float(d.get("sensor_fault_flag", 0)) * 3)
    d["health_deficit"]     = 100 - d["health_index"]
    d["overdue_days"]       = max(0.0, float(d.get("days_since_last_service", 0)) - 60)
    d["breakdown_history"]  = float(d.get("lifetime_breakdown_count", 0))
    d["service_intensity"]  = float(d.get("lifetime_service_count", 0)) / (age + 1)

    parts = str(d.get("parts_replaced_last_service", ""))
    for tok in bundle["part_tokens"]:
        d[f"part_{tok}"] = int(tok in parts)

    # [NEW v5] target-encoded service_vehicle -> smoothed mean(cost/fuel_price).
    # Unseen service_vehicle combinations (e.g. a next_service_type/vehicle_type
    # pairing not present in training) fall back to the global mean rather than
    # raising or silently defaulting to 0.
    d["svc_cost_te"] = float(bundle["svc_te_map"].get(d["service_vehicle"], bundle["svc_te_global"]))

    return d


def _prep_matrices(eng: dict, b: dict):
    """Build CatBoost (Xc) and LightGBM/XGBoost (Xg) input matrices."""
    row = {c: eng.get(c) for c in b["feature_cols"]}
    X   = pd.DataFrame([row])

    Xc = X.copy()
    for c in b["categorical_cols"]:
        Xc[c] = Xc[c].astype(str).fillna("__missing__")
    for c in b["numeric_cols"]:
        Xc[c] = pd.to_numeric(Xc[c], errors="coerce").fillna(0.0)
    Xc = Xc[b["feature_cols"]]

    Xg = X.copy()
    for c in b["categorical_cols"]:
        Xg[c] = Xg[c].astype(str).fillna("__missing__").astype(b["gbm_dtypes"][c])
    for c in b["numeric_cols"]:
        Xg[c] = pd.to_numeric(Xg[c], errors="coerce").fillna(0.0)
    Xg = Xg[b["feature_cols"]]

    return Xc, Xg


def predict_breakdown_cost(raw_input: dict, bundle: dict, top_k: int = 5) -> dict:
    """
    Predict the cost this asset will incur IF it requires maintenance in the next 30 days.

    Signature and return shape are IDENTICAL to v4 — no caller changes needed.

    Parameters
    ----------
    raw_input : dict   Asset fields from DB (same shape as _build_cost_input in predictions.py)
    bundle    : dict   From load_breakdown_bundle()
    top_k     : int    SHAP drivers to return

    Returns
    -------
    {
      predicted_cost_lkr    float   Point estimate in LKR
      pi_80_lower_lkr       float   Calibrated 80% PI lower bound
      pi_80_upper_lkr       float   Calibrated 80% PI upper bound
      coverage_target       str     "80%"
      fleet_mean_lkr        float   Mean of training target (LKR 51,871)
      vs_fleet_mean_lkr     float   predicted - fleet mean
      expected_range        dict    {"p25_lkr": ..., "p75_lkr": ...}
      sanity_check          str     "within_expected" | "below_expected" | "above_expected"
      top_drivers           list    SHAP drivers
        feature             str
        value               str
        direction           str     "increases" | "decreases"
        relative_impact     float   |sv[j]| / Σ|sv| × 100
        sv_log              float   Raw SHAP in log-ratio space (not LKR — never display directly)
    }
    """
    b   = bundle
    eng = _engineer(raw_input, b)
    Xc, Xg = _prep_matrices(eng, b)

    # Select the right matrix per predictor family
    # CatBoost → Xc (string categoricals); XGBoost / LightGBM → Xg (category dtype)
    Xpred = Xc if b["predictor_name"] == "CatBoost" else Xg

    # [CHANGED v5] model predicts log1p(cost / fuel_price) — rescale by the
    # input's own fuel_price_lkr_per_l to recover LKR. Guard against a
    # missing/zero fuel price so we never divide-by-zero or multiply by 0.
    fuel_price = float(raw_input.get("fuel_price_lkr_per_l", 0)) or 1e-6

    log_ratio_pred = float(b["predictor_model"].predict(Xpred)[0])
    point = float(np.expm1(max(0.0, log_ratio_pred)) * fuel_price)

    # 80% PI — always LightGBM quantile models → always Xg. Same rescaling.
    lo = float(max(0.0,
        np.expm1(max(0.0, float(b["q10"].predict(Xg)[0]))) * fuel_price - b["conformal_q_hat"]
    ))
    hi = float(np.expm1(float(b["q90"].predict(Xg)[0])) * fuel_price + b["conformal_q_hat"])

    # The point and the interval come from different models — CatBoost for the
    # value, the two LightGBM quantile models above for the bounds — and nothing
    # in training constrains them to agree. On live fleet data roughly half the
    # assets returned lo > point, i.e. an "80% interval" that excludes its own
    # estimate, which then rendered as a nonsense range on the asset report.
    # Widen the interval to contain the point rather than moving the point:
    # the estimate stays exactly what the predictor said, and the bounds stay
    # the quantile models' own numbers except where they contradict it.
    lo = min(lo, point)
    hi = max(hi, point)

    # SHAP — computed in log-ratio space, same as v4's log1p(cost) space.
    # sv_log is intentionally not LKR-denominated; never display it directly.
    if b["predictor_name"] == "CatBoost":
        sf  = b["predictor_model"].get_feature_importance(
            Pool(Xc, cat_features=b["categorical_cols"]), type="ShapValues"
        )
        sv  = sf[0, :-1]
    else:
        sv = b["shap_explainer"].shap_values(Xpred)[0]

    total_abs = float(np.abs(sv).sum()) or 1e-9
    top = np.argsort(np.abs(sv))[::-1][:top_k]
    drivers: list[dict] = []
    for j in top:
        v = Xpred.iloc[0, j]
        if hasattr(v, "item"): v = v.item()
        sv_j = float(sv[j])
        col_name = Xpred.columns[j]

        # svc_cost_te is a target-encoded statistic (mean historical cost/fuel-price
        # ratio for this service+vehicle combo) — showing its raw float value
        # ("289.27") means nothing to an admin. Surface it as the human-readable
        # service+vehicle combination it actually represents instead.
        if col_name == "svc_cost_te":
            feature_label = "service_type_cost_pattern"
            sv_str = str(eng.get("service_vehicle", ""))
            if "__" in sv_str:
                svc_part, veh_part = sv_str.split("__", 1)
                value_display = f"{svc_part.replace('_',' ').title()} · {veh_part.replace('_',' ')}"
            else:
                value_display = sv_str or str(v)
        else:
            feature_label = col_name
            value_display = str(v)

        drivers.append({
            "feature"         : feature_label,
            "value"           : value_display,
            "direction"       : "increases" if sv_j > 0 else "decreases",
            "relative_impact" : round(abs(sv_j) / total_abs * 100, 1),
            "sv_log"          : round(sv_j, 6),
        })

    # Sanity check vs training distribution
    nsv  = str(raw_input.get("next_service_type") or raw_input.get("last_service_type") or "")
    rng  = b["expected_ranges"].get(nsv)
    if rng:
        sanity = ("within_expected" if rng[0] <= point <= rng[1]
                  else "below_expected" if point < rng[0] else "above_expected")
        expected_range = {"p25_lkr": round(rng[0], 0), "p75_lkr": round(rng[1], 0)}
    else:
        sanity, expected_range = "unknown_service_type", {}

    test_metrics = b.get("test_metrics", {})
    return {
        "predicted_cost_lkr"  : round(point, 2),
        "pi_80_lower_lkr"     : round(lo, 2),
        "pi_80_upper_lkr"     : round(hi, 2),
        "coverage_target"     : "80%",
        "fleet_mean_lkr"      : round(b["fleet_mean_lkr"], 2),
        "vs_fleet_mean_lkr"   : round(point - b["fleet_mean_lkr"], 2),
        "expected_range"      : expected_range,
        "sanity_check"        : sanity,
        "top_drivers"         : drivers,
        "test_r2"             : round(float(test_metrics.get("R2", 0.0)), 4) if test_metrics else None,
        "test_mae_lkr"        : round(float(test_metrics.get("MAE", 0.0)), 2) if test_metrics else None,
        "test_medae_lkr"      : round(float(test_metrics.get("MedAE", 0.0)), 2) if test_metrics else None,
        "picp_80_pct"         : round(float(b.get("picp_80_test", 0.0)) * 100, 1),
    }