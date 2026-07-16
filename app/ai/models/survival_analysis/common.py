"""
Shared configuration for the per-component survival-analysis pipeline (v3).

Everything downstream — dataset builder, trainer, inference service, and the
two report apps — imports its schema from here so the feature contract stays
consistent end-to-end.

Design notes
------------
* We train ONE Weibull AFT model per core component (brake, tire, battery,
  oil, hydraulic). Each is an "expert" on its own part.
* Survival target is taken directly from the real v11 dataset, no synthetic
  time sampling:
      duration_days = days_until_next_maintenance          (forward gap)
      event         = 1 if next_service_type == this component's service
                      else 0  (right-censored — a *different* part, or nothing,
                               was serviced next, so this part survived at least
                               `duration_days`).
* Because every service resets `days_since_last_service`, the model reads a
  single most-recent snapshot and returns a survival curve — no continuous
  degradation history required. This is what solves the two problems the OLS
  approach hit (sparse readings; discontinuities at each service).
"""

from __future__ import annotations

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
# The one and only dataset we train / report on (v11).
HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv"
# Fall back to the copy that lives next to the 2rd-model folder if not colocated.
if not DATASET_PATH.exists():
    DATASET_PATH = (
        HERE.parent
        / "Training set 2rd model"
        / "srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv"
    )

DATA_DIR   = HERE / "data"
MODELS_DIR = HERE / "models"
REPORTS_DIR = HERE / "reports"

TRAIN_CSV = DATA_DIR / "survival_snapshots_train.csv"
TEST_CSV  = DATA_DIR / "survival_snapshots_test.csv"

# ── Core components ─────────────────────────────────────────────────────────────
COMPONENTS = ["brake", "tire", "battery", "oil", "hydraulic"]

# component -> the `next_service_type` / `last_service_type` token that means
# "this component was serviced/replaced".
COMPONENT_SERVICE = {
    "brake":     "brake_service",
    "tire":      "tire_service",
    "battery":   "battery_service",
    "oil":       "oil_service",
    "hydraulic": "hydraulic_service",
}

# component -> the health/condition column that most directly reflects its state.
COMPONENT_HEALTH_COL = {
    "brake":     "brake_health_pct",
    "tire":      "tire_health_pct",
    "battery":   "battery_health_pct",
    "oil":       "oil_life_pct",
    "hydraulic": "hydraulic_health_pct",
}

# component -> fields the cost-estimation model expects to price a replacement.
# Values match the categorical vocab of the cost / PdM models (v11).
COMPONENT_COST_PROFILE = {
    "brake":     {"last_service_type": "brake_service",     "major_component_replaced": "brake_system",
                  "parts_replaced_last_service": "brake_pads;discs;fluid"},
    "tire":      {"last_service_type": "tire_service",      "major_component_replaced": "tires",
                  "parts_replaced_last_service": "tires;valves"},
    "battery":   {"last_service_type": "battery_service",   "major_component_replaced": "battery",
                  "parts_replaced_last_service": "battery;terminals"},
    "oil":       {"last_service_type": "oil_service",       "major_component_replaced": "none",
                  "parts_replaced_last_service": "engine_oil;oil_filter"},
    "hydraulic": {"last_service_type": "hydraulic_service", "major_component_replaced": "hydraulic_pump",
                  "parts_replaced_last_service": "hydraulic_pump;seals;fluid"},
}

# ── Survival target columns ─────────────────────────────────────────────────────
DURATION_COL = "duration_days"
EVENT_COL    = "event"

# Source columns in v11 used to derive the target.
LABEL_SOURCE_COLS = ["next_service_type", "days_until_next_maintenance"]

# ── Feature schema ──────────────────────────────────────────────────────────────
ID_COLS = ["vehicle_id", "snapshot_date", "warehouse_id"]

CATEGORICAL_COLS = ["vehicle_type", "vehicle_role"]

# Shared stress / context / wear covariates fed to every component model.
SHARED_NUMERIC_COLS = [
    "vehicle_age_years", "payload_capacity_kg",
    "lifetime_service_count", "lifetime_breakdown_count",
    "odometer_km", "engine_hours_total",
    "vibration_rms_mm_s", "engine_hours_since_last_service",
    "days_since_last_service", "mileage_since_last_service_km",
    "active_fault_code_count", "sensor_fault_flag",
    "payload_utilization_pct", "overload_events_30d",
    "downtime_hours_last_90d", "start_stop_burden_30d",
    "engine_temp_avg_c", "coolant_temp_max_c",
    "ambient_temp_avg_c", "ambient_humidity_avg_pct", "rainfall_mm_30d",
    "rough_road_pct", "urban_route_pct", "port_route_pct",
]

# All health columns are carried in the snapshot table; each model keeps only
# its OWN health column as a predictor (see feature_cols_for_component).
ALL_HEALTH_COLS = list(COMPONENT_HEALTH_COL.values())

# Columns persisted to the snapshot train/test CSVs.
SNAPSHOT_COLS = (
    ID_COLS
    + CATEGORICAL_COLS
    + SHARED_NUMERIC_COLS
    + ALL_HEALTH_COLS
    + LABEL_SOURCE_COLS
)


def feature_cols_for_component(component: str) -> list[str]:
    """Raw (pre-one-hot) predictor columns for one component's model."""
    return SHARED_NUMERIC_COLS + [COMPONENT_HEALTH_COL[component]] + CATEGORICAL_COLS


def derive_target(df, component: str):
    """
    Given a snapshot frame, return (duration_series, event_series) for one
    component using the real forward-looking labels.
    """
    service_token = COMPONENT_SERVICE[component]
    duration = df["days_until_next_maintenance"].astype(float).clip(lower=1.0)
    event = (df["next_service_type"] == service_token).astype(int)
    return duration, event


def transform_design(df_raw, schema):
    """
    Turn a raw feature frame into the model design matrix EXACTLY as it was at
    training time. Used by both the trainer and the inference service so there
    is a single source of truth for the transform.

    Steps: z-score numeric cols with the stored scaler, one-hot the categoricals
    (drop_first), then reindex to the stored feature column order (missing dummy
    columns filled with 0 for unseen categories).
    """
    import pandas as pd

    df = df_raw.copy()
    for col, (mean, std) in schema["scaler"].items():
        vals = pd.to_numeric(df.get(col), errors="coerce").fillna(mean)
        df[col] = (vals - mean) / (std if std else 1.0)
    for col in schema["categorical_cols"]:
        if col not in df.columns:
            df[col] = "__missing__"
        df[col] = df[col].astype(str)
    df = pd.get_dummies(df, columns=schema["categorical_cols"], drop_first=True)
    bool_cols = df.select_dtypes(include="bool").columns
    df[bool_cols] = df[bool_cols].astype(int)
    for col in schema["feature_cols"]:
        if col not in df.columns:
            df[col] = 0
    return df[schema["feature_cols"]]


def build_schema(train_raw, component: str):
    """Compute scaler stats + final one-hot feature column order from train data."""
    import pandas as pd

    numeric_cols = SHARED_NUMERIC_COLS + [COMPONENT_HEALTH_COL[component]]
    scaler = {}
    for col in numeric_cols:
        vals = pd.to_numeric(train_raw[col], errors="coerce")
        mean = float(vals.mean())
        std = float(vals.std(ddof=0)) or 1.0
        scaler[col] = [mean, std]

    tmp = train_raw.copy()
    for col in numeric_cols:
        mean, std = scaler[col]
        tmp[col] = (pd.to_numeric(tmp[col], errors="coerce").fillna(mean) - mean) / std
    tmp = pd.get_dummies(tmp, columns=CATEGORICAL_COLS, drop_first=True)
    feature_cols = [c for c in tmp.columns if c in numeric_cols
                    or any(c.startswith(f"{cat}_") for cat in CATEGORICAL_COLS)]

    return {
        "component":        component,
        "duration_col":     DURATION_COL,
        "event_col":        EVENT_COL,
        "numeric_cols":     numeric_cols,
        "categorical_cols": CATEGORICAL_COLS,
        "health_col":       COMPONENT_HEALTH_COL[component],
        "feature_cols":     feature_cols,
        "scaler":           scaler,
    }


# Horizons (days) used by the report apps.
HORIZONS = [7, 30]
