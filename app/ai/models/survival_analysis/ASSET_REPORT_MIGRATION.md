# Asset Report — migration to the v3 survival endpoints

> The **warehouse** report was migrated to the new v3 survival models in this
> change. The **asset** report was intentionally left as-is. This guide shows how
> to move the asset report onto the same v3 models when you're ready. No asset
> code was changed — everything below is additive.

---

## 1. What already changed (backend)

`app/ai/services/survival_service.py` now loads the **v3** per-component Weibull
AFT models (`{brake,tire,battery,oil,hydraulic}_aft.pkl` + `_features.json` in
this folder). The two asset endpoints are **unchanged in shape** — they keep
working with no client change:

| Endpoint | Purpose |
|---|---|
| `GET /survival/{asset_id}` | all 5 components for one asset |
| `GET /survival/{asset_id}/{component}` | one component's curve |

Two things improved under the hood, transparently:

1. **Numbers now come from the v3 models** (trained on the real v11 dataset;
   held-out c-index 0.78–0.89), scored on the asset's **live** `SensorReading`.
2. **`p10_days` / `p90_days` are now correctly ordered** (`p10 < median < p90`).
   The old service had them inverted vs. their own schema docstrings; the v3
   service matches the docstrings (`p10` = "90% sure it still works past this
   day", `p90` = "only 10% chance of surviving past").

The service *also computes* new per-component fields (`fail_prob_7d`,
`fail_prob_30d`, `survival_7d`, `survival_30d`, `health_pct`) — but they are
currently **stripped by the Pydantic response model**, so clients don't see them
yet. Step 2 exposes them.

---

## 2. Step 1 — expose the new fields (one small schema edit)

The new fields already flow out of `predict_all_components` /
`predict_survival_curve`; they're dropped only because `schemas/survival.py`
doesn't declare them. Add them as **optional** fields (backward compatible — old
clients ignore them):

```python
# app/schemas/survival.py

class ComponentSurvivalResponse(BaseModel):
    asset_id: str
    component: Component
    median_days: float
    p10_days: float
    p90_days: float
    curve: list[SurvivalCurvePoint]
    # ── new v3 fields (optional; safe to add) ──
    health_pct:    float | None = None
    survival_7d:   float | None = None
    survival_30d:  float | None = None
    fail_prob_7d:  float | None = None
    fail_prob_30d: float | None = None
```

That's the **only** backend edit needed. No service, router, or model change.

---

## 3. Step 2 — what `GET /survival/{asset_id}` now returns

```jsonc
{
  "asset_id": "…uuid…",
  "horizon_days": 180,
  "step_days": 14,
  "soonest_component": "oil",
  "soonest_median_days": 331.18,
  "components": [
    {
      "asset_id": "…uuid…",
      "component": "oil",
      "health_pct": 84.1,
      "median_days": 331.18,
      "p10_days": 56.26,          // early / safe day (90% still working)
      "p90_days": 1024.86,        // late day (only 10% still working)
      "fail_prob_7d": 0.0114,     // ← NEW: P(fail within 7 days)
      "fail_prob_30d": 0.0526,    // ← NEW: P(fail within 30 days)
      "survival_7d": 0.9886,
      "survival_30d": 0.9474,
      "curve": [ {"day":0,"survival_prob":1.0}, {"day":14,"survival_prob":0.98}, … ]
    }
    // … brake, tire, battery, hydraulic …
  ]
}
```

`soonest_component` is the part to plan a spare for. Each component carries its
own `health_pct`, 7/30-day failure probability, median RUL and p10–p90 band.

---

## 4. Step 3 — recommended asset-report layout

Mirror the warehouse report's asset view (proven in the training folder's
`asset_report.py`):

1. **Five survival curves** — plot each component's `curve` (`day` vs
   `survival_prob`) on one chart; mark 7d and 30d verticals. The curve that
   drops first = soonest failure.
2. **Component risk table** — one row per component:
   `health_pct · fail_prob_7d · fail_prob_30d · median_days · p10–p90`,
   with the `soonest_component` row highlighted and the 30-day cell shaded by
   risk.
3. **Cost line** — pull the replacement estimate from the existing cost model,
   **do not recompute it**:

   ```
   GET /predictions/cost/{asset_id}
   → { estimated_cost, min_cost, max_cost, currency }
   ```

No new cost model is involved — same source the warehouse report uses.

---

## 5. Field reference

| Field | Meaning | Use in asset report |
|---|---|---|
| `fail_prob_7d` / `fail_prob_30d` | P(component fails within 7 / 30 days) | risk table, 7/30d badges |
| `survival_7d` / `survival_30d` | `1 − fail_prob` | optional |
| `median_days` | p50 remaining life | "best guess" RUL |
| `p10_days` / `p90_days` | 90% / 10% survival day (p10 < p90) | uncertainty band |
| `health_pct` | current condition of that component | context column |
| `soonest_component` | lowest-median component | headline / spare to bring |
| `curve[]` | `{day, survival_prob}` series | the survival-curve chart |

---

## 6. Optional — a single call for the asset page

If you'd rather fetch survival **and** cost in one request, add a thin composite
endpoint (leaves the existing ones intact):

```python
# app/routers/survival_predictions.py  (illustrative)
@router.get("/{asset_id}/report")
def asset_survival_report(asset_id: str, db: Session = Depends(get_db)):
    survival = survival_service.predict_all_components(db, asset_id)
    cost = (db.query(AssetCostPrediction)
              .filter(AssetCostPrediction.asset_id == asset_id)
              .order_by(AssetCostPrediction.created_at.desc()).first())
    return {
        "survival": survival,
        "cost": {
            "estimated_cost": float(cost.estimated_cost) if cost else None,
            "min_cost": float(cost.min_cost) if cost else None,
            "max_cost": float(cost.max_cost) if cost else None,
            "currency": cost.currency if cost else "LKR",
        } if cost else None,
    }
```

---

## 7. Checklist

- [ ] Add the 5 optional fields to `ComponentSurvivalResponse` (§2).
- [ ] Asset report reads `fail_prob_7d` / `fail_prob_30d` + `curve` from
      `GET /survival/{asset_id}`.
- [ ] Cost from `GET /predictions/cost/{asset_id}` (existing cost model).
- [ ] Verify `p10_days < median_days < p90_days` in the UI (ordering fix).

*No changes to the asset report were made in this commit — this document is the
plan for when you migrate it.*
