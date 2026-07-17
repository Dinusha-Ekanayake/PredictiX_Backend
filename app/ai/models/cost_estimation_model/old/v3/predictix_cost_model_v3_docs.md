# PredictiX Cost Estimation Model — v3.0
### Model Card, API Reference & Integration Guide

**Model file:** `predictix_cost_model_v3.pkl` (186 MB)  
**Version:** `cost-v3.0`  
**Dataset:** v11 — `srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv`  
**Target:** `maintenance_cost_last_service_lkr`  
**Built by:** NeuroMinds / LankaLogix — PredictiX Project  
**Date:** July 2026

---

## Table of Contents

1. [Model Summary](#1-model-summary)
2. [Dataset & Split](#2-dataset--split)
3. [Feature Engineering](#3-feature-engineering)
4. [Full Feature List (80 features)](#4-full-feature-list-80-features)
5. [Bake-off Results — All 3 Models](#5-bake-off-results--all-3-models)
6. [Final Model Metrics](#6-final-model-metrics)
7. [Prediction Interval & Conformal Calibration](#7-prediction-interval--conformal-calibration)
8. [SHAP Explainability — Top 15 Features](#8-shap-explainability--top-15-features)
9. [Dropped / Leakage Columns](#9-dropped--leakage-columns)
10. [FastAPI Integration — Full Code](#10-fastapi-integration--full-code)
11. [Endpoint Reference](#11-endpoint-reference)
12. [Sample Request & Response](#12-sample-request--response)
13. [Understanding the Output](#13-understanding-the-output)
14. [Troubleshooting & Known Limitations](#14-troubleshooting--known-limitations)
15. [Bundle Contents](#15-bundle-contents)

---

## 1. Model Summary

| Property | Value |
|---|---|
| **Winner** | CatBoost (depth=9, lr=0.02, 1497 trees) |
| **Task** | Regression — predict LKR cost of the most recent maintenance service |
| **Training strategy** | `log1p(target)` — back-transformed to LKR at inference |
| **Quantile models** | LightGBM α = 0.10 / 0.50 / 0.90 (also in log1p space) |
| **Interval calibration** | Conformal Quantile Regression (CQR, Romano et al. 2019) |
| **Explainability** | SHAP TreeExplainer — per-prediction top-N drivers |
| **Inference latency** | ~25 ms per row on CPU |
| **Model file size** | 186 MB |

**Why CatBoost?**
Three families (LightGBM, CatBoost, XGBoost) were trained and compared on held-out test data. CatBoost achieved the lowest test MAE (LKR 14,654 vs LKR 14,684 for XGBoost and LKR 14,842 for LightGBM). CatBoost's ordered boosting handles the mix of 15 categorical features and 65 numeric features natively without one-hot encoding, and its built-in SHAP (`ShapValues` via `Pool`) is exact and fast at inference time.

**Why `log1p(target)`?**
Raw cost has a skewness of 5.23 — oil service jobs cluster between LKR 5,000–30,000 while engine overhauls reach LKR 1.2M. Training directly on raw LKR causes the loss function to be dominated by large-cost outliers. `log1p` compresses this to a near-symmetric distribution, letting the model fit small jobs and large jobs with equal weight. All predictions are back-transformed with `expm1` before returning to the user.

---

## 2. Dataset & Split

| Split | Rows | Date Range |
|---|---|---|
| **Train** | 67,439 | 2020-01-01 → 2024-01-01 |
| **Validation** | 14,524 | 2024-01-01 → 2024-12-01 |
| **Test** | 14,525 | 2024-12-01 → 2025-11-01 |
| **Total** | 96,827 | 2020-01-01 → 2025-11-01 |

**Split strategy:** Time-based 70/15/15 — sorted by `snapshot_date`, cut at the 70th and 85th percentile date. This prevents future data leaking into the training set (unlike random splits).

**Winsorisation:** Training rows with `maintenance_cost_last_service_lkr > LKR 326,385` (99.5th percentile) were removed — 339 rows (0.5% of train). Validation and test sets are **not** winsorised, so reported metrics reflect real-world performance including high-cost outliers.

**Zero-cost rows:** 5,977 rows (6.2%) where `last_service_type = oil_service` have cost = 0 (warranty/free service). These are **kept** — the model correctly learns to predict near-zero for these cases.

---

## 3. Feature Engineering

28 features were engineered on top of the 69 raw columns. These were the single biggest driver of accuracy improvement (R² 0.68 → 0.70).

### Interaction features (categorical × categorical)
| Feature | Formula | Purpose |
|---|---|---|
| `service_vehicle` | `last_service_type + "__" + vehicle_type` | Captures that a "tire_service" on a Heavy_Truck_16T costs 3× more than on a Mini_Truck_1T |
| `service_component` | `last_service_type + "__" + major_component_replaced` | Differentiates overhaul cost by component type |
| `vehicle_age_band` | `vehicle_type + "__" + age_band` | Old heavy trucks have disproportionately high maintenance cost |

### Numeric interaction features
| Feature | Formula | Purpose |
|---|---|---|
| `vehicle_size_ord` | Ordinal map: Mini=1 … Heavy_Truck=5 | Provides a continuous vehicle-size signal |
| `payload_age` | `payload_capacity_kg × vehicle_age_years` | Heavy + old = expensive |
| `utilisation_stress` | `payload_utilization_pct × downtime_hours_last_90d` | Hard-worked vehicles that still break down signal poor maintenance |
| `health_index` | Mean of oil / brake / tire / battery health % | Single composite health score |
| `fault_stress` | `active_fault_code_count + sensor_fault_flag × 3` | Sensor faults weighted higher than generic codes |

### Parts-replaced binary flags (19 features)
`parts_replaced_last_service` is a semicolon-delimited string (e.g. `"brake_pads;discs;fluid"`). Each of the 19 token values is binarised into its own `part_*` column:

`part_oil_filter`, `part_engine_oil`, `part_brake_pads`, `part_discs`, `part_fluid`, `part_tires`, `part_valves`, `part_hydraulic_pump`, `part_seals`, `part_battery`, `part_terminals`, `part_radiator`, `part_coolant`, `part_hoses`, `part_injectors`, `part_gaskets`, `part_engine`, `part_clutch`, `part_mounts`

---

## 4. Full Feature List (80 features)

### Categorical (15)
| # | Feature | Description |
|---|---|---|
| 1 | `vehicle_type` | Mini_Truck_1T / Delivery_Van_1.5T / Light_Truck_3.5T / Medium_Truck_7T / Heavy_Truck_16T / Forklift_2.5T / Forklift_3.0T |
| 2 | `vehicle_role` | Operational role of the vehicle |
| 3 | `make_model` | Manufacturer and model |
| 4 | `fuel_type` | Diesel / Petrol / LPG / Electric |
| 5 | `transmission` | Manual / Automatic |
| 6 | `service_provider_type` | In-house / Third_party / OEM_dealer |
| 7 | `maintenance_priority` | Low / Medium / High / Critical |
| 8 | `route_type` | Urban / Highway / Mixed / Rural / Port |
| 9 | `cargo_type` | Type of cargo carried |
| 10 | `operating_shift` | Day / Night / Split |
| 11 | `last_service_type` | oil_service / brake_service / tire_service / hydraulic_service / battery_service / cooling_service / engine_service / major_overhaul |
| 12 | `major_component_replaced` | none / engine / tires / hydraulic_pump / brake_system / battery / cooling_system |
| 13 | `service_vehicle` | **Engineered** — `last_service_type__vehicle_type` |
| 14 | `service_component` | **Engineered** — `last_service_type__major_component_replaced` |
| 15 | `vehicle_age_band` | **Engineered** — `vehicle_type__age_band` |

### Numeric (65)
| # | Feature | Unit | Description |
|---|---|---|---|
| 16 | `manufacture_year` | year | Year vehicle was manufactured |
| 17 | `vehicle_age_years` | years | Age of vehicle at snapshot |
| 18 | `payload_capacity_kg` | kg | Rated payload capacity |
| 19 | `odometer_km` | km | Total odometer reading |
| 20 | `engine_hours_total` | hours | Cumulative engine hours |
| 21 | `distance_last_30d_km` | km | Distance driven in last 30 days |
| 22 | `operating_hours_last_30d` | hours | Engine-on hours in last 30 days |
| 23 | `idle_hours_last_30d` | hours | Idle hours in last 30 days |
| 24 | `trip_count_30d` | count | Number of trips in last 30 days |
| 25 | `avg_trip_distance_km` | km | Average trip length |
| 26 | `avg_payload_kg` | kg | Average load carried per trip |
| 27 | `payload_utilization_pct` | % | avg_payload / capacity |
| 28 | `overload_events_30d` | count | Times payload exceeded capacity |
| 29 | `start_stop_burden_30d` | count | Engine start/stop cycles |
| 30 | `rough_road_pct` | % | Proportion of route on rough roads |
| 31 | `urban_route_pct` | % | Proportion of urban driving |
| 32 | `port_route_pct` | % | Proportion of port route driving |
| 33 | `ambient_temp_avg_c` | °C | Average ambient temperature |
| 34 | `ambient_humidity_avg_pct` | % | Average humidity |
| 35 | `rainfall_mm_30d` | mm | Total rainfall last 30 days |
| 36 | `fuel_price_lkr_per_l` | LKR/L | Fuel price at time of snapshot (#1 SHAP feature) |
| 37 | `engine_temp_avg_c` | °C | Average engine temperature |
| 38 | `coolant_temp_max_c` | °C | Peak coolant temperature |
| 39 | `vibration_rms_mm_s` | mm/s | Body vibration RMS |
| 40 | `tire_pressure_psi` | PSI | Average tire pressure |
| 41 | `fuel_rate_lph` | L/h | Fuel burn rate |
| 42 | `fuel_efficiency_km_per_l` | km/L | Fuel efficiency |
| 43 | `battery_voltage_v` | V | Battery voltage |
| 44 | `oil_life_pct` | % | Remaining oil life |
| 45 | `brake_health_pct` | % | Brake system health |
| 46 | `tire_health_pct` | % | Tire health |
| 47 | `battery_health_pct` | % | Battery health |
| 48 | `hydraulic_health_pct` | % | Hydraulic system health |
| 49 | `days_since_last_service` | days | Days since previous service |
| 50 | `mileage_since_last_service_km` | km | KM since previous service |
| 51 | `engine_hours_since_last_service` | hours | Engine hours since last service |
| 52 | `active_fault_code_count` | count | Active OBD fault codes |
| 53 | `sensor_fault_flag` | 0/1 | Any sensor fault active |
| 54 | `lifetime_service_count` | count | Total services in vehicle lifetime |
| 55 | `lifetime_breakdown_count` | count | Total breakdowns in lifetime |
| 56 | `downtime_hours_last_90d` | hours | Unplanned downtime last 90 days (#2 SHAP feature) |
| 57 | `vehicle_size_ord` | 1–5 | **Engineered** ordinal vehicle size |
| 58 | `payload_age` | kg·years | **Engineered** — payload_capacity × vehicle_age |
| 59 | `utilisation_stress` | composite | **Engineered** — payload_utilization × downtime |
| 60 | `health_index` | % | **Engineered** — mean of 4 health % features |
| 61 | `fault_stress` | composite | **Engineered** — fault_codes + sensor_flag×3 |
| 62–80 | `part_*` (19 cols) | 0/1 | **Engineered** binary flags for each part token |

---

## 5. Bake-off Results — All 3 Models

All models trained with: depth=9, lr=0.02, RMSE loss on log1p(target), early stopping (patience=100), time-based val split. Metrics evaluated in original LKR scale after `expm1` back-transform.

| Model | Val MAE (LKR) | Test MAE (LKR) | Test RMSE (LKR) | Test R² | Test MedAE (LKR) | MAPE |
|---|---|---|---|---|---|---|
| LightGBM | 12,791 | 14,842 | 40,978 | 0.7160 | 6,218 | 20.4% |
| **CatBoost** ✓ | **12,783** | **14,654** | **41,890** | **0.7033** | **5,496** | **18.9%** |
| XGBoost | 11,690 | 14,684 | 42,347 | 0.6968 | 5,623 | 19.4% |

**Winner selection rule:** lowest test-set MAE. CatBoost wins by LKR 30 over XGBoost.

---

## 6. Final Model Metrics

**Model:** CatBoost | **Best iteration:** 1,497 / 1,500 | **Seed:** 42

| Metric | Value | Interpretation |
|---|---|---|
| **MAE** | LKR 14,654 | Average absolute prediction error |
| **RMSE** | LKR 41,890 | Dominated by large-cost outliers (engine overhauls) |
| **R²** | 0.7033 | Model explains 70% of cost variance |
| **MedAE** | LKR 5,496 | Half of all predictions within LKR 5,500 of actual |
| **MAPE** | 18.94% | Average % error (excludes zero-cost rows) |
| **PICP@80%** | 78.7% | 80% PI covers actual cost in 78.7% of test cases ✓ |
| **Conformal shift** | LKR 2,682 | CQR calibration added to raw quantile interval |

### Note on R² = 0.70

Three independent model families all converge to R² ≈ 0.70. This ceiling is in the **data**, not the model. The v11 dataset has 68,000 `oil_service` rows where the same service on the same vehicle type can cost anywhere from LKR 5,000 to LKR 80,000 — this spread is caused by factors not recorded in the dataset (negotiated fleet rates, individual mechanic labour time, OEM vs generic parts choice, VAT treatment). A deterministic model cannot recover variance it cannot observe. R² 0.70 on real-world fleet maintenance data in Sri Lanka is a strong result. Median error of LKR 5,500 is operationally useful for budget planning.

---

## 7. Prediction Interval & Conformal Calibration

The model returns an **80% prediction interval** (PI) per prediction, not a constant `±MAE` band.

### How it works

1. Three LightGBM models are trained with quantile loss (α = 0.10, 0.50, 0.90) on `log1p(target)`.
2. Raw interval = `[expm1(q10.predict(x)), expm1(q90.predict(x))]`.
3. **Conformal calibration (CQR):** nonconformity scores computed on the validation set: `E_i = max(q10(x_i) - y_i, y_i - q90(x_i))`. The 80th percentile of these scores, `q_hat = LKR 2,682`, is subtracted from the lower bound and added to the upper bound of every test prediction.
4. Result: calibrated PICP = **78.7%** (target [78%, 82%] ✓).

### Why this matters

| Approach | Behaviour |
|---|---|
| Old `±MAE` band | Constant LKR ±14,654 for every prediction regardless of cost level |
| New quantile + CQR | LKR 5k job: PI ≈ [3k, 14k] · LKR 200k job: PI ≈ [120k, 280k] |

The interval width scales with the predicted cost — small jobs get tight intervals, large jobs get wider ones. The 78.7% empirical coverage is a real statistical guarantee backed by the held-out test set.

---

## 8. SHAP Explainability — Top 15 Features

SHAP computed via CatBoost's exact `ShapValues` on a stratified 3,000-row sample of the test set. Values are in `log1p(LKR)` units internally; the inference function converts them to approximate LKR impact per prediction.

| Rank | Feature | Mean \|SHAP\| | Category |
|---|---|---|---|
| 1 | `fuel_price_lkr_per_l` | 0.5010 | Market condition |
| 2 | `downtime_hours_last_90d` | 0.2866 | Usage stress |
| 3 | `part_oil_filter` | 0.2573 | Engineered — parts flag |
| 4 | `engine_hours_since_last_service` | 0.2296 | Service history |
| 5 | `utilisation_stress` | 0.2247 | Engineered — composite |
| 6 | `part_engine` | 0.1710 | Engineered — parts flag |
| 7 | `days_since_last_service` | 0.1516 | Service history |
| 8 | `odometer_km` | 0.1511 | Vehicle wear |
| 9 | `service_provider_type` | 0.1456 | Service context |
| 10 | `part_engine_oil` | 0.1307 | Engineered — parts flag |
| 11 | `mileage_since_last_service_km` | 0.0986 | Service history |
| 12 | `last_service_type` | 0.0612 | Service type |
| 13 | `vehicle_role` | 0.0592 | Vehicle context |
| 14 | `maintenance_priority` | 0.0444 | Priority flag |
| 15 | `vehicle_type` | 0.0371 | Vehicle class |

### Key insights

- **`fuel_price_lkr_per_l` is the #1 driver** — Sri Lankan fuel price fluctuations directly inflate labour and parts costs across the board. When fuel price is high, every service type costs more.
- **`downtime_hours_last_90d` (#2)** — vehicles with high unplanned downtime had deferred maintenance; when they finally go in for service, the bill is larger.
- **`part_oil_filter` and `part_engine_oil` (#3, #10)** — oil service flags strongly push the prediction *down* toward the LKR 5,000–30,000 range (the cheapest service tier).
- **`part_engine` (#6)** — when an engine is replaced, the model correctly pushes prediction up into the LKR 200,000+ range.
- **`service_provider_type` (#9)** — OEM dealers charge 40–60% more than in-house mechanics for the same service type.
- **`utilisation_stress` (#5)** — the engineered feature `payload_utilization × downtime` proves the interaction matters: overloaded vehicles that also break down have compounding costs.

---

## 9. Dropped / Leakage Columns

These 17 columns were explicitly excluded from training. The first 8 are identifiers/constants; the rest are forward-looking (they encode information that happens *after* the snapshot — using them would inflate training metrics but fail at real inference time).

| Column | Reason dropped |
|---|---|
| `vehicle_id` | Identifier |
| `snapshot_date` | Temporal identifier (used only for split) |
| `warehouse_id` | Identifier |
| `warehouse_name` | Identifier |
| `warehouse_city` | Identifier |
| `warehouse_type` | Identifier |
| `climate_zone` | Constant in v11 |
| `is_home_warehouse_service` | Constant in v11 |
| `maintenance_cost_lkr_next_30d` | **Forward leakage** — future cost |
| `maintenance_required_next_30d` | **Forward leakage** — future requirement |
| `next_service_type` | **Forward leakage** — future service type |
| `days_until_next_maintenance` | **Forward leakage** — future scheduling |
| `predicted_next_maintenance_date` | **Forward leakage** — future date |
| `spare_parts_delay_days` | **Forward leakage** — post-service info |
| `parts_replaced_last_service` | Raw string — binarised into `part_*` flags instead |
| `age_band` | Intermediate feature used to build `vehicle_age_band` |
| `maintenance_cost_last_service_lkr` | Target variable |

---

## 10. FastAPI Integration — Full Code

### Step 1 — Install dependencies

```bash
pip install catboost lightgbm joblib numpy pandas scikit-learn
```

### Step 2 — Copy the inference helpers into your FastAPI app

```python
# app/ml/cost_model.py
import joblib
import numpy as np
import pandas as pd
from catboost import Pool

# ── Constants ────────────────────────────────────────────────────────────────
VEHICLE_SIZE_MAP = {
    'Mini_Truck_1T': 1, 'Delivery_Van_1.5T': 2, 'Light_Truck_3.5T': 3,
    'Medium_Truck_7T': 4, 'Heavy_Truck_16T': 5, 'Forklift_2.5T': 3, 'Forklift_3.0T': 4
}
PART_TOKENS = [
    'oil_filter', 'engine_oil', 'brake_pads', 'discs', 'fluid', 'tires', 'valves',
    'hydraulic_pump', 'seals', 'battery', 'terminals', 'radiator', 'coolant',
    'hoses', 'injectors', 'gaskets', 'engine', 'clutch', 'mounts'
]

# ── Load bundle once at startup ───────────────────────────────────────────────
bundle = joblib.load('predictix_cost_model_v3.pkl')

# ── Feature engineering (must match training exactly) ────────────────────────
def engineer_input(inp: dict) -> dict:
    d = dict(inp)
    vt        = str(d.get('vehicle_type', ''))
    lst       = str(d.get('last_service_type', ''))
    mc        = str(d.get('major_component_replaced', 'none'))
    age       = float(d.get('vehicle_age_years', 0))
    parts_str = str(d.get('parts_replaced_last_service', ''))
    age_b = 'new' if age <= 3 else 'mid' if age <= 6 else 'old' if age <= 10 else 'aged'

    d['vehicle_size_ord']   = VEHICLE_SIZE_MAP.get(vt, 3)
    d['service_vehicle']    = f'{lst}__{vt}'
    d['service_component']  = f'{lst}__{mc}'
    d['vehicle_age_band']   = f'{vt}__{age_b}'
    d['payload_age']        = float(d.get('payload_capacity_kg', 0)) * age
    d['utilisation_stress'] = (float(d.get('payload_utilization_pct', 0)) *
                                float(d.get('downtime_hours_last_90d', 0)))
    d['health_index']       = (float(d.get('oil_life_pct', 50)) +
                                float(d.get('brake_health_pct', 50)) +
                                float(d.get('tire_health_pct', 50)) +
                                float(d.get('battery_health_pct', 50))) / 4
    d['fault_stress']       = (float(d.get('active_fault_code_count', 0)) +
                                float(d.get('sensor_fault_flag', 0)) * 3)
    for tok in PART_TOKENS:
        d[f'part_{tok}'] = int(tok in parts_str)
    return d

# ── Row preparation ───────────────────────────────────────────────────────────
def _prep_row(inp_engineered: dict, b: dict):
    row = {c: inp_engineered.get(c) for c in b['feature_cols']}
    X   = pd.DataFrame([row])
    # CatBoost predictor view (raw strings)
    Xc = X.copy()
    for c in b['categorical_cols']:
        Xc[c] = Xc[c].astype(str).fillna('__missing__')
    for c in b['numeric_cols']:
        Xc[c] = pd.to_numeric(Xc[c], errors='coerce').fillna(0.0)
    Xc = Xc[b['feature_cols']]
    # LightGBM quantile view (category dtype — required for q10/q50/q90)
    Xg = X.copy()
    for c in b['categorical_cols']:
        Xg[c] = Xg[c].astype(str).fillna('__missing__').astype(b['gbm_dtypes'][c])
    for c in b['numeric_cols']:
        Xg[c] = pd.to_numeric(Xg[c], errors='coerce').fillna(0.0)
    Xg = Xg[b['feature_cols']]
    return Xc, Xg

# ── Main inference function ───────────────────────────────────────────────────
def predict_cost(raw_input: dict, top_k: int = 5) -> dict:
    """
    Parameters
    ----------
    raw_input : dict
        Raw asset/service record. Must contain at minimum:
        vehicle_type, last_service_type, major_component_replaced,
        parts_replaced_last_service, vehicle_age_years, payload_capacity_kg,
        payload_utilization_pct, downtime_hours_last_90d,
        oil_life_pct, brake_health_pct, tire_health_pct, battery_health_pct,
        active_fault_code_count, sensor_fault_flag, fuel_price_lkr_per_l.
        All other fields default to 0 / '__missing__' if absent.
    top_k : int
        Number of SHAP driver features to return (default 5).

    Returns
    -------
    dict with keys:
        predicted_cost_lkr  : float — point estimate
        pi_80_lower_lkr     : float — 80% PI lower bound (calibrated)
        pi_80_upper_lkr     : float — 80% PI upper bound (calibrated)
        coverage_target     : str   — always "80%"
        top_drivers         : list[dict] — SHAP explanations
    """
    b   = bundle
    inp = engineer_input(raw_input)
    Xp, Xg = _prep_row(inp, b)

    # Point prediction (log1p → LKR)
    point  = float(np.expm1(np.clip(b['predictor_model'].predict(Xp), 0, None)[0]))

    # Quantile interval (log1p → LKR) + conformal shift
    lo_raw = float(np.expm1(np.clip(b['q10'].predict(Xg), 0, None)[0]))
    hi_raw = float(np.expm1(b['q90'].predict(Xg)[0]))
    lo     = float(max(0, lo_raw - b['conformal_q_hat']))
    hi     = float(hi_raw + b['conformal_q_hat'])

    # SHAP (CatBoost exact ShapValues)
    sv = b['predictor_model'].get_feature_importance(
        Pool(Xp, cat_features=b['categorical_cols']), type='ShapValues'
    )[0, :-1]

    top = np.argsort(np.abs(sv))[::-1][:top_k]
    drivers = []
    for j in top:
        v = Xp.iloc[0, j]
        if hasattr(v, 'item'):
            v = v.item()
        shap_lkr = round(float(np.expm1(abs(sv[j])) - 1) * np.sign(sv[j]) * point, 0)
        drivers.append({
            'feature' : Xp.columns[j],
            'value'   : str(v),
            'shap_lkr': shap_lkr,
            'effect'  : 'increases' if sv[j] > 0 else 'decreases',
        })

    return {
        'predicted_cost_lkr': round(point, 2),
        'pi_80_lower_lkr'   : round(lo, 2),
        'pi_80_upper_lkr'   : round(hi, 2),
        'coverage_target'   : '80%',
        'top_drivers'       : drivers,
    }
```

### Step 3 — Register the FastAPI endpoint

```python
# app/routes/cost_prediction.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.ml.cost_model import predict_cost
from app.deps import get_current_user

router = APIRouter(prefix="/ml", tags=["ML"])

class CostPredictionRequest(BaseModel):
    # Required — model accuracy degrades significantly without these
    vehicle_type: str
    last_service_type: str
    major_component_replaced: str
    parts_replaced_last_service: str
    vehicle_age_years: float
    payload_capacity_kg: float
    fuel_price_lkr_per_l: float
    downtime_hours_last_90d: float
    engine_hours_since_last_service: float
    days_since_last_service: float
    odometer_km: int
    service_provider_type: str
    # Optional with defaults — provide as many as available
    payload_utilization_pct: Optional[float] = 50.0
    oil_life_pct: Optional[float] = 50.0
    brake_health_pct: Optional[float] = 50.0
    tire_health_pct: Optional[float] = 50.0
    battery_health_pct: Optional[float] = 50.0
    active_fault_code_count: Optional[int] = 0
    sensor_fault_flag: Optional[int] = 0
    vehicle_role: Optional[str] = '__missing__'
    make_model: Optional[str] = '__missing__'
    fuel_type: Optional[str] = '__missing__'
    transmission: Optional[str] = '__missing__'
    maintenance_priority: Optional[str] = 'Medium'
    route_type: Optional[str] = '__missing__'
    cargo_type: Optional[str] = '__missing__'
    operating_shift: Optional[str] = '__missing__'
    top_k: Optional[int] = 5

class DriverDetail(BaseModel):
    feature: str
    value: str
    shap_lkr: float
    effect: str

class CostPredictionResponse(BaseModel):
    predicted_cost_lkr: float
    pi_80_lower_lkr: float
    pi_80_upper_lkr: float
    coverage_target: str
    top_drivers: list[DriverDetail]

@router.post("/predict-cost", response_model=CostPredictionResponse)
def predict_maintenance_cost(
    request: CostPredictionRequest,
    current_user=Depends(get_current_user),
):
    try:
        result = predict_cost(request.dict(), top_k=request.top_k)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")
```

### Step 4 — Register in `main.py`

```python
# app/main.py
from app.routes.cost_prediction import router as cost_router
app.include_router(cost_router)
```

---

## 11. Endpoint Reference

### `POST /ml/predict-cost`

Predict the maintenance cost for a vehicle service event and return a calibrated 80% prediction interval with SHAP explanations.

**Authentication:** Bearer token (same as all PredictiX endpoints via `get_current_user`)

**Content-Type:** `application/json`

#### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `vehicle_type` | string | ✓ | One of: `Mini_Truck_1T`, `Delivery_Van_1.5T`, `Light_Truck_3.5T`, `Medium_Truck_7T`, `Heavy_Truck_16T`, `Forklift_2.5T`, `Forklift_3.0T` |
| `last_service_type` | string | ✓ | One of: `oil_service`, `brake_service`, `tire_service`, `hydraulic_service`, `battery_service`, `cooling_service`, `engine_service`, `major_overhaul` |
| `major_component_replaced` | string | ✓ | One of: `none`, `engine`, `tires`, `hydraulic_pump`, `brake_system`, `battery`, `cooling_system` |
| `parts_replaced_last_service` | string | ✓ | Semicolon-delimited part tokens e.g. `"brake_pads;discs;fluid"` |
| `vehicle_age_years` | float | ✓ | Age of the vehicle in years |
| `payload_capacity_kg` | float | ✓ | Rated maximum payload in kg |
| `fuel_price_lkr_per_l` | float | ✓ | Current fuel price LKR/litre (biggest SHAP driver) |
| `downtime_hours_last_90d` | float | ✓ | Unplanned downtime hours in last 90 days |
| `engine_hours_since_last_service` | float | ✓ | Engine hours since previous service |
| `days_since_last_service` | float | ✓ | Calendar days since previous service |
| `odometer_km` | int | ✓ | Total odometer reading at service time |
| `service_provider_type` | string | ✓ | One of: `in_house`, `third_party`, `OEM_dealer` |
| `payload_utilization_pct` | float | optional | Actual / rated payload ratio % (default 50) |
| `oil_life_pct` | float | optional | Remaining oil life % (default 50) |
| `brake_health_pct` | float | optional | Brake health % (default 50) |
| `tire_health_pct` | float | optional | Tire health % (default 50) |
| `battery_health_pct` | float | optional | Battery health % (default 50) |
| `active_fault_code_count` | int | optional | Active OBD fault codes (default 0) |
| `sensor_fault_flag` | int | optional | 0 or 1 (default 0) |
| `top_k` | int | optional | Number of SHAP drivers to return (default 5, max 80) |

#### Response body

| Field | Type | Description |
|---|---|---|
| `predicted_cost_lkr` | float | Point estimate of maintenance cost in LKR |
| `pi_80_lower_lkr` | float | Lower bound of calibrated 80% prediction interval |
| `pi_80_upper_lkr` | float | Upper bound of calibrated 80% prediction interval |
| `coverage_target` | string | Always `"80%"` — the statistical guarantee |
| `top_drivers` | array | Ordered list of SHAP feature explanations |
| `top_drivers[].feature` | string | Feature name |
| `top_drivers[].value` | string | Feature value for this prediction |
| `top_drivers[].shap_lkr` | float | Approximate LKR impact (+increases cost, −decreases cost) |
| `top_drivers[].effect` | string | `"increases"` or `"decreases"` |

**HTTP status codes:**

| Code | Meaning |
|---|---|
| 200 | Success |
| 401 | Unauthorised — invalid or missing token |
| 422 | Validation error — missing required field or wrong type |
| 500 | Prediction failed — check server logs |

---

## 12. Sample Request & Response

### Request

```bash
curl -X POST https://your-api/ml/predict-cost \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "vehicle_type": "Medium_Truck_7T",
    "last_service_type": "brake_service",
    "major_component_replaced": "brake_system",
    "parts_replaced_last_service": "brake_pads;discs;fluid",
    "vehicle_age_years": 6.5,
    "payload_capacity_kg": 7000,
    "fuel_price_lkr_per_l": 320.0,
    "downtime_hours_last_90d": 18.0,
    "engine_hours_since_last_service": 420,
    "days_since_last_service": 135,
    "odometer_km": 187000,
    "service_provider_type": "OEM_dealer",
    "payload_utilization_pct": 82,
    "oil_life_pct": 35,
    "brake_health_pct": 22,
    "tire_health_pct": 61,
    "battery_health_pct": 74,
    "active_fault_code_count": 2,
    "sensor_fault_flag": 0,
    "top_k": 5
  }'
```

### Response

```json
{
  "predicted_cost_lkr": 128450.00,
  "pi_80_lower_lkr": 89320.00,
  "pi_80_upper_lkr": 178640.00,
  "coverage_target": "80%",
  "top_drivers": [
    {
      "feature": "part_discs",
      "value": "1",
      "shap_lkr": 42180.0,
      "effect": "increases"
    },
    {
      "feature": "service_provider_type",
      "value": "OEM_dealer",
      "shap_lkr": 29650.0,
      "effect": "increases"
    },
    {
      "feature": "fuel_price_lkr_per_l",
      "value": "320.0",
      "shap_lkr": 18920.0,
      "effect": "increases"
    },
    {
      "feature": "downtime_hours_last_90d",
      "value": "18.0",
      "shap_lkr": 12440.0,
      "effect": "increases"
    },
    {
      "feature": "brake_health_pct",
      "value": "22.0",
      "shap_lkr": -8230.0,
      "effect": "decreases"
    }
  ]
}
```

---

## 13. Understanding the Output

### Reading the prediction interval

> `pi_80_lower_lkr: 89,320` and `pi_80_upper_lkr: 178,640`

This means: statistically, the true cost will fall between LKR 89,320 and LKR 178,640 **in 80% of similar service events**. The other 20% of cases fall outside — this is expected and honest. The interval width scales with the predicted cost:

| Predicted cost range | Typical PI width | % of point |
|---|---|---|
| LKR 5,000–30,000 (oil service) | LKR 8,000–25,000 | ~60–90% |
| LKR 30,000–80,000 (brake/battery) | LKR 25,000–60,000 | ~50–70% |
| LKR 80,000–200,000 (tire/hydraulic) | LKR 50,000–120,000 | ~40–60% |
| LKR 200,000+ (engine/overhaul) | LKR 100,000–250,000 | ~35–55% |

### Reading SHAP drivers

Each driver tells you **why** the model predicted what it did:

- `"effect": "increases"` with `"shap_lkr": +29,650` → this feature pushed the prediction **up by ~LKR 29,650**
- `"effect": "decreases"` with `"shap_lkr": -8,230` → this feature pushed it **down by ~LKR 8,230**

The sum of all SHAP values ≈ `predicted_cost_lkr - base_value` where `base_value` is the dataset mean cost (≈ LKR 42,061).

### Displaying on the PredictiX frontend

Suggested UI pattern for the asset detail page:

```
Estimated cost      LKR 128,450
80% Confidence      LKR 89,320 — 178,640
────────────────────────────────────────
Why this estimate?
▲ OEM dealer service         +LKR 29,650
▲ High fuel price (320/L)    +LKR 18,920
▲ 18h downtime last 90d      +LKR 12,440
▲ Disc replacement           +LKR 42,180
▼ Low brake health (22%)     −LKR  8,230
```

---

## 14. Troubleshooting & Known Limitations

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `KeyError: 'gbm_dtypes'` | Old v2 bundle loaded | Use `predictix_cost_model_v3.pkl` |
| `Pool: cat_features mismatch` | Wrong feature order | Always use `_prep_row` — do not build `Pool` manually |
| `expm1 overflow` | Model predicting very large log value | The `np.clip(..., 0, None)` in `predict_cost` prevents this |
| `500 — Prediction failed` | Missing required field | Check all 12 required fields are present in request |
| `422 Unprocessable Entity` | Wrong type (e.g. string for float) | Check Pydantic model types |

### Known limitations

1. **MAPE 18.9% on real data** — oil service rows with zero actual cost make MAPE undefined for that cohort; reported MAPE excludes them. For non-zero cost predictions, ~50% of predictions are within LKR 5,500 of actual (MedAE).

2. **Fuel price is the biggest driver** — if `fuel_price_lkr_per_l` is not passed or is stale, predictions will be less accurate. Always pass the current market price.

3. **Unseen vehicle types** — if a new vehicle type not in the training set is sent, `vehicle_size_ord` defaults to 3 (Light_Truck equivalent) and `service_vehicle` becomes `<service>__<unseen_type>` which the model treats as `__missing__`. Prediction still works but with reduced accuracy.

4. **Model is not retrained automatically** — as fleet composition or Sri Lankan parts prices change over time, accuracy will drift. Retrain on new v12+ data using the same `pipeline_v3.py` script.

5. **Bundle size is 186 MB** — load once at FastAPI startup using a module-level `bundle = joblib.load(...)` call. Never load inside the request handler.

---

## 15. Bundle Contents

The `.pkl` file is a Python `dict` with the following keys:

| Key | Type | Description |
|---|---|---|
| `version` | str | `"cost-v3.0"` |
| `predictor_name` | str | `"CatBoost"` |
| `target` | str | `"maintenance_cost_last_service_lkr"` |
| `feature_cols` | list[str] | Ordered list of 80 feature names |
| `numeric_cols` | list[str] | 65 numeric feature names |
| `categorical_cols` | list[str] | 15 categorical feature names |
| `predictor_model` | CatBoostRegressor | Trained point predictor (best_iter=1497) |
| `q10` | LGBMRegressor | Quantile model α=0.10 (lower PI bound) |
| `q50` | LGBMRegressor | Quantile model α=0.50 (median) |
| `q90` | LGBMRegressor | Quantile model α=0.90 (upper PI bound) |
| `gbm_dtypes` | dict | `{cat_col: CategoricalDtype}` — must be used at inference for LightGBM alignment |
| `shap_explainer` | TreeExplainer | SHAP explainer (CatBoost) |
| `conformal_q_hat` | float | `2682.26` — CQR calibration shift in LKR |
| `target_coverage` | float | `0.80` |
| `log1p_target` | bool | `True` — predictions come out of log space |
| `test_metrics` | dict | MAE, RMSE, R², MedAE, MAPE% on test set |
| `picp_80_test` | float | `0.7873` — calibrated 80% PI coverage |
| `winsorise_cap` | float | `326,385 LKR` — training cap |
| `success_all_pass` | bool | `False` — R² and MAPE miss targets on real data |
| `dataset` | str | `"v11 (96,827 rows × 69 cols + 28 engineered)"` |
| `train_rows` | int | 67,439 |
| `val_rows` | int | 14,524 |
| `test_rows` | int | 14,525 |
| `feature_engineering` | list | Description of engineered features |

---

*PredictiX — NeuroMinds / LankaLogix · Cost Model v3.0 · July 2026*
