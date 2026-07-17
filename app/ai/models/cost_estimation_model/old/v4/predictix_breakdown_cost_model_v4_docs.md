# PredictiX Breakdown Cost Estimation Model — v4.0
### Model Card, API Reference & Integration Guide

**Model file:** `predictix_breakdown_cost_model_v4.pkl` (104 MB)  
**Inference module:** `app/ai/models/cost_estimation_model/breakdown_cost_model.py`  
**Version:** `breakdown-cost-v4.0`  
**Dataset:** v11 — filtered to `maintenance_required_next_30d == 1` and `cost > 0`  
**Target:** `maintenance_cost_lkr_next_30d`

---

## Why v4 replaces v3

| | v3 (old) | v4 (this model) |
|---|---|---|
| **Target** | `maintenance_cost_last_service_lkr` | `maintenance_cost_lkr_next_30d` |
| **Direction** | Backward — cost of the *last* service | Forward — cost *if* asset breaks/services next |
| **Aligns with SHAP risk factors?** | No — different feature drivers | Yes — oil life, battery, days overdue |
| **Useful for asset detail page?** | No — stale info | Yes — predicts what the *current health state* will cost |
| **Training rows** | 96,827 (all rows) | 28,113 (maintenance_required=1 only) |

---

## 1. Model Summary

| Property | Value |
|---|---|
| **Winner** | XGBoost (depth=9, lr=0.02, 1,752 trees) |
| **Training target** | `log1p(maintenance_cost_lkr_next_30d)` back-transformed at inference |
| **Quantile models** | LightGBM α = 0.10 / 0.50 / 0.90 |
| **Calibration** | Conformal QR (CQR) — conformal shift LKR 2,301 |
| **SHAP** | `shap.TreeExplainer` on XGBoost via category-dtype matrix |
| **Inference** | ~15ms per asset on CPU |

---

## 2. Dataset & Split

| Split | Rows | Date Range |
|---|---|---|
| **Train** | 19,580 | 2020 → 2024-01 |
| **Val** | 4,217 | 2024-01 → 2024-12 |
| **Test** | 4,217 | 2024-12 → 2025-11 |

**Filter:** Only rows where `maintenance_required_next_30d == 1` and `maintenance_cost_lkr_next_30d > 0`.  
This gives the model rows where a real maintenance event is about to happen — training it to learn  
*what it will cost given the current health state*, not what the last service cost.

**Winsorisation:** Training rows with cost > LKR 376,054 (99.5th %ile) removed (49 rows, 0.25%).

---

## 3. Bake-off Results

| Model | Val MAE | Test MAE | Test R² | Test MedAE | MAPE |
|---|---|---|---|---|---|
| LightGBM | 13,592 | 16,688 | 0.5646 | 5,378 | 18.1% |
| CatBoost | 13,576 | 16,459 | 0.5905 | 5,394 | 17.7% |
| **XGBoost ✓** | **13,242** | **15,459** | **0.6426** | **5,216** | **17.8%** |

**PICP@80%:** 79.2% after conformal calibration ✓ (target [78%, 82%])

### Note on R² = 0.64
Same structural reason as v3: cost variance is driven partly by factors not in the dataset  
(individual mechanic rates, OEM vs generic parts, negotiated fleet contracts).  
**MedAE of LKR 5,216** means half of all predictions are within LKR 5,200 of actual — operationally useful.

---

## 4. New Engineered Features (v4-specific)

| Feature | Formula | Why |
|---|---|---|
| `service_vehicle` | `next_service_type__vehicle_type` | Top SHAP feature — service type × vehicle size interaction |
| `health_deficit` | `100 - health_index` | Direct degradation signal — higher = more worn |
| `overdue_days` | `max(0, days_since_last_service - 60)` | Days beyond the 60-day standard interval |
| `breakdown_history` | `lifetime_breakdown_count` | Assets with prior breakdowns cost more |
| `service_intensity` | `lifetime_service_count / (age + 1)` | Service frequency normalised by age |

---

## 5. Top 15 SHAP Features

| Rank | Feature | Mean \|SHAP\| | Interpretation |
|---|---|---|---|
| 1 | `service_vehicle` | 0.5237 | Brake service on Forklift_2.5T → ~LKR 47k; engine on Heavy_Truck → LKR 190k+ |
| 2 | `fuel_price_lkr_per_l` | 0.1644 | Sri Lanka fuel price directly scales parts and labour cost |
| 3 | `service_provider_type` | 0.1550 | OEM dealer 40–60% more expensive than in-house |
| 4 | `oil_life_pct` | 0.0612 | Low oil life → likely overdue → higher cost |
| 5 | `maintenance_priority` | 0.0483 | Critical priority → typically costlier corrective jobs |
| 6 | `odometer_km` | 0.0324 | Higher mileage → more worn components |
| 7 | `payload_capacity_kg` | 0.0243 | Heavier vehicles cost more to service |
| 8 | `payload_age` | 0.0241 | payload_capacity × age — compound stress factor |
| 9 | `vehicle_type` | 0.0206 | Heavy_Truck_16T costs 5× more than Mini_Truck_1T |
| 10 | `manufacture_year` | 0.0186 | Older vehicles → costlier parts |
| 11 | `vehicle_age_years` | 0.0185 | Correlated with manufacture_year |
| 12 | `make_model` | 0.0157 | OEM brand parts pricing |
| 13 | `engine_hours_total` | 0.0143 | Cumulative engine wear |
| 14 | `hydraulic_health_pct` | 0.0091 | Low hydraulic health → likely hydraulic service needed |
| 15 | `days_since_last_service` | 0.0075 | Overdue days signal deferred maintenance |

---

## 6. API Endpoint

### `GET /predictions/cost/{asset_id}`

Returns the breakdown cost prediction for an asset.

**Behaviour:**
1. Checks the `AssetCostPrediction` DB table for a cached result.
2. If no cached result → runs the model live, writes to DB, returns immediately.
3. If model not loaded → 503.

**Auth:** Bearer token

**Response:**
```json
{
  "id": "uuid",
  "asset_id": "uuid",
  "run_id": null,
  "estimated_cost": 46773.87,
  "confidence_lower": 44398.62,
  "confidence_upper": 69761.46,
  "model_version": "breakdown-cost-v4.0",
  "extra_data": {
    "predicted_cost_lkr": 46773.87,
    "pi_80_lower_lkr": 44398.62,
    "pi_80_upper_lkr": 69761.46,
    "coverage_target": "80%",
    "fleet_mean_lkr": 51870.86,
    "vs_fleet_mean_lkr": -5097.0,
    "expected_range": { "p25_lkr": 37500, "p75_lkr": 84088 },
    "sanity_check": "within_expected",
    "top_drivers": [
      {
        "feature": "service_vehicle",
        "value": "brake_service__Forklift_2.5T",
        "direction": "increases",
        "relative_impact": 31.5,
        "sv_log": 0.357659
      }
    ]
  },
  "created_at": "2026-07-11T..."
}
```

### `POST /predictions/cost/live/{asset_id}`

Force-runs the model bypassing cache. Always writes a new DB record.  
Useful after a maintenance event to refresh the estimate.

---

## 7. File Locations

```
app/
├── main.py                                         ← load_breakdown_bundle() at startup
├── routers/
│   └── predictions.py                              ← GET /predictions/cost/{asset_id}
├── ai/
│   ├── models/
│   │   └── cost_estimation_model/
│   │       ├── __init__.py
│   │       ├── predictix_breakdown_cost_model_v4.pkl   ← model bundle (104 MB)
│   │       └── breakdown_cost_model.py                 ← inference module
│   └── services/
│       └── batch_prediction_service.py             ← writes cost to AssetCostPrediction
```

---

## 8. SLW0668 Example (Forklift_2.5T, 11yr, 102d overdue)

Asset state from the detail page:
- Oil life 77%, Tire health 50%, Brake 74%, Battery 77%, Hydraulic 73%
- 40 lifetime services, 3 lifetime breakdowns, 102 days since last service (overdue)
- Predicted next service: brake_service

Model output:
```
Predicted cost  : LKR 46,773.87
80% PI          : LKR 44,398.62  →  LKR 69,761.46
Expected range  : LKR 37,500 – 84,088  (brake_service P25–P75)
Sanity check    : within_expected ✓
```

Top SHAP drivers:
| Feature | Direction | Impact % |
|---|---|---|
| `service_vehicle` (brake_service__Forklift_2.5T) | increases | 31.5% |
| `service_provider_type` | decreases | 16.6% |
| `oil_life_pct` (77%) | increases | 10.3% |
| `fuel_price_lkr_per_l` (310) | increases | 8.4% |

---

## 9. Display Guidance (Frontend)

```
Maintenance Cost Estimate
LKR 46,774

Minimum    LKR 44,399
Estimated  LKR 46,774
Maximum    LKR 69,761
Coverage: 80% statistical confidence

Why this estimate?
▲ brake_service on Forklift_2.5T    31.5%  ████████████████
▲ Current oil life (77%)            10.3%  █████
▲ Fuel price LKR 310/L               8.4%  ████
▼ Service provider (in-house)       16.6%  ████████

Model: XGBoost v4.0 · Dataset: v11 · R²=0.64 · MedAE=LKR 5,216
```

Use `relative_impact` for bar chart width (0–100%).  
Use `direction` for colour (red = increases cost, green = decreases).  
**Never display `sv_log` directly** — it is in log1p space.

---

*PredictiX — NeuroMinds / LankaLogix · Breakdown Cost Model v4.0 · July 2026*
