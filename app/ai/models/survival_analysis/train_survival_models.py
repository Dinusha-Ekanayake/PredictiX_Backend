"""
Train five per-component Weibull AFT survival models on the real v11 panel,
then bundle them into one unified artifact.

Reads:
    data/survival_snapshots_train.csv
    data/survival_snapshots_test.csv   (produced by build_survival_dataset.py)

Writes (into models/):
    {component}_aft.pkl        — fitted lifelines WeibullAFTFitter
    {component}_features.json  — feature schema + scaler (for inference parity)
    survival_bundle.pkl        — all 5 models + schemas in one file (unified model)
    training_report.json       — metrics for every component

Usage:
    python train_survival_models.py
    python train_survival_models.py --component brake --penalizer 0.05
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime

import pandas as pd
from lifelines import WeibullAFTFitter
from lifelines.utils import concordance_index

import common as C


def train_one(train_raw: pd.DataFrame, test_raw: pd.DataFrame,
              component: str, penalizer: float):
    schema = C.build_schema(train_raw, component)

    # Design matrices (identical transform for train + test).
    X_train = C.transform_design(train_raw[C.feature_cols_for_component(component)], schema)
    X_test  = C.transform_design(test_raw[C.feature_cols_for_component(component)], schema)

    dur_tr, evt_tr = C.derive_target(train_raw, component)
    dur_te, evt_te = C.derive_target(test_raw, component)

    fit_df = X_train.copy()
    fit_df[C.DURATION_COL] = dur_tr.values
    fit_df[C.EVENT_COL]    = evt_tr.values

    # Resample to address the extremely low event rate (2-4%) for non-oil components.
    # We downsample the censored snapshots so that the event rate is ~20%,
    # bringing the median_days prediction into a realistic range.
    events_df = fit_df[fit_df[C.EVENT_COL] == 1]
    censored_df = fit_df[fit_df[C.EVENT_COL] == 0]
    
    target_censored = int(4 * len(events_df))
    if target_censored < len(censored_df):
        censored_sampled = censored_df.sample(n=target_censored, random_state=42)
        fit_df = pd.concat([events_df, censored_sampled]).sample(frac=1, random_state=42).reset_index(drop=True)

    aft = WeibullAFTFitter(penalizer=penalizer)
    aft.fit(fit_df, duration_col=C.DURATION_COL, event_col=C.EVENT_COL)

    # Concordance on held-out vehicles: higher predicted median => later failure.
    pred_median = aft.predict_median(X_test)
    c_index = concordance_index(
        event_times=dur_te.values,
        predicted_scores=pred_median.values,
        event_observed=evt_te.values,
    )

    # Top covariates on lambda_ (scale) — drivers of median life.
    try:
        lam = aft.params_.xs("lambda_", level=0).drop(labels=["Intercept"], errors="ignore")
        ranked = lam.abs().sort_values(ascending=False).head(6).index
        top = [{"feature": f, "coef": round(float(lam[f]), 4)} for f in ranked]
    except Exception:
        top = []

    metrics = {
        "component":        component,
        "n_train_rows":     int(len(X_train)),
        "n_test_rows":      int(len(X_test)),
        "n_train_events":   int(evt_tr.sum()),
        "n_test_events":    int(evt_te.sum()),
        "event_rate_train": round(float(evt_tr.mean()), 4),
        "n_features":       len(schema["feature_cols"]),
        "log_likelihood":   round(float(aft.log_likelihood_), 2),
        "AIC":              round(float(aft.AIC_), 2),
        "weibull_rho":      round(float(aft.rho_.iloc[0]) if hasattr(aft, "rho_") else float("nan"), 4),
        "test_concordance": round(float(c_index), 4),
        "top_covariates":   top,
    }
    return aft, schema, metrics


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--component", default=None, help="train one component (default: all 5)")
    p.add_argument("--penalizer", type=float, default=0.02,
                   help="L2 ridge penalty on AFT coefficients")
    args = p.parse_args()

    if not C.TRAIN_CSV.exists():
        raise SystemExit(f"Missing {C.TRAIN_CSV}. Run: python build_survival_dataset.py")

    C.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    train_raw = pd.read_csv(C.TRAIN_CSV)
    test_raw  = pd.read_csv(C.TEST_CSV)

    components = [args.component] if args.component else C.COMPONENTS
    bundle = {"version": "survival-v3.0", "components": {}, "component_list": components}
    all_metrics = []

    for comp in components:
        print(f"\n── Training {comp} " + "─" * 44)
        aft, schema, metrics = train_one(train_raw, test_raw, comp, args.penalizer)

        with open(C.MODELS_DIR / f"{comp}_aft.pkl", "wb") as f:
            pickle.dump(aft, f)
        with open(C.MODELS_DIR / f"{comp}_features.json", "w") as f:
            json.dump(schema, f, indent=2)

        bundle["components"][comp] = {"model": aft, "schema": schema}

        print(f"  rows train/test : {metrics['n_train_rows']:,} / {metrics['n_test_rows']:,}")
        print(f"  events tr/te    : {metrics['n_train_events']:,} / {metrics['n_test_events']:,} "
              f"(rate {metrics['event_rate_train']:.1%})")
        print(f"  AIC             : {metrics['AIC']}")
        print(f"  Weibull rho     : {metrics['weibull_rho']}")
        print(f"  test c-index    : {metrics['test_concordance']}")
        if metrics["top_covariates"]:
            print("  top covariates  :")
            for tc in metrics["top_covariates"]:
                sign = "↑longer" if tc["coef"] > 0 else "↓shorter"
                print(f"      {tc['feature']:<34s} coef={tc['coef']:+.4f}  ({sign} life)")
        all_metrics.append(metrics)

    with open(C.MODELS_DIR / "survival_bundle.pkl", "wb") as f:
        pickle.dump(bundle, f)

    report = {
        "trained_at": datetime.utcnow().isoformat() + "Z",
        "version":    "survival-v3.0",
        "dataset":    C.DATASET_PATH.name,
        "penalizer":  args.penalizer,
        "target":     "duration_days = days_until_next_maintenance; "
                      "event = (next_service_type == component service)",
        "components": all_metrics,
    }
    with open(C.MODELS_DIR / "training_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n── Summary " + "─" * 50)
    print(f"{'component':<12s} {'c-index':>9s} {'events tr/te':>16s} {'AIC':>12s}")
    for m in all_metrics:
        ev = f"{m['n_train_events']}/{m['n_test_events']}"
        print(f"  {m['component']:<10s} {m['test_concordance']:>9.4f} {ev:>16s} {m['AIC']:>12.0f}")
    print(f"\nWrote unified bundle : {C.MODELS_DIR / 'survival_bundle.pkl'}")
    print(f"Wrote training report: {C.MODELS_DIR / 'training_report.json'}")


if __name__ == "__main__":
    main()
