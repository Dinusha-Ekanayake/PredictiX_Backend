"""Batch predictions router.

Endpoints
---------
GET  /batch-predictions/            — latest cached prediction for every asset
GET  /batch-predictions/{asset_id}  — latest cached prediction for one asset
POST /batch-predictions/run         — trigger a full batch run immediately
POST /batch-predictions/run/{asset_id} — re-run predictions for one asset
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Asset, PdmBatchPrediction
from app.ai.services.batch_prediction_service import (
    run_batch_for_all_assets,
    run_batch_for_asset,
)

router = APIRouter(prefix="/batch-predictions", tags=["Batch Predictions"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _serialize(row: PdmBatchPrediction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "asset_id": str(row.asset_id),
        "failure_probability": float(row.failure_probability) if row.failure_probability is not None else None,
        "maintenance_required": row.maintenance_required,
        "risk_level": row.risk_level,
        "predicted_days_until_maintenance": row.predicted_days_until_maintenance,
        "predicted_maintenance_date": str(row.predicted_maintenance_date) if row.predicted_maintenance_date else None,
        "health_score": float(row.health_score) if row.health_score is not None else None,
        "health_status": row.health_status,
        "contributing_factors": row.contributing_factors or [],
        "estimated_cost_lkr": float(row.estimated_cost_lkr) if row.estimated_cost_lkr is not None else None,
        "min_cost_lkr": float(row.min_cost_lkr) if row.min_cost_lkr is not None else None,
        "max_cost_lkr": float(row.max_cost_lkr) if row.max_cost_lkr is not None else None,
        "top_explanations": row.top_explanations or [],
        "predicted_at": row.predicted_at.isoformat() if row.predicted_at else None,
        "run_duration_ms": row.run_duration_ms,
        "status": row.status,
        "error_message": row.error_message,
    }


# ── read endpoints ─────────────────────────────────────────────────────────────

@router.get("/", summary="Latest cached PDM predictions for all assets")
def list_batch_predictions(db: Session = Depends(get_db)) -> list[dict]:
    """Returns the most recent pre-computed prediction for every asset that
    has been processed by the batch scheduler."""
    rows = (
        db.query(PdmBatchPrediction)
        .order_by(PdmBatchPrediction.predicted_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


@router.get("/{asset_id}", summary="Latest cached PDM prediction for one asset")
def get_batch_prediction(asset_id: str, db: Session = Depends(get_db)) -> dict:
    """Returns the latest cached prediction for a specific asset."""
    row = (
        db.query(PdmBatchPrediction)
        .filter(PdmBatchPrediction.asset_id == asset_id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No batch prediction found for asset {asset_id}. "
                   "The scheduler may not have run yet — call POST /batch-predictions/run to trigger.",
        )
    return _serialize(row)


# ── trigger endpoints ──────────────────────────────────────────────────────────

@router.post("/run", summary="Trigger a full batch prediction run for all assets")
def trigger_full_batch(db: Session = Depends(get_db)) -> dict:
    """Immediately runs the PDM pipeline for every active asset and upserts
    results.  Useful as a Render/Railway cron job target or for manual refresh.

    This is a *synchronous* endpoint — it blocks until the run completes.
    For large fleets this may take a while; consider calling from a cron job
    rather than from a user-facing UI.
    """
    from app.main import clf_model, clf_features, clf_threshold, clf_categorical_cols, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=503, detail="ML models are not loaded yet")

    result = run_batch_for_all_assets(
        db=db,
        clf_model=clf_model,
        clf_features=clf_features,
        clf_threshold=clf_threshold,
        clf_categorical_cols=clf_categorical_cols,
        reg_model=reg_model,
        reg_features=reg_features,
    )
    return result


@router.post("/run/{asset_id}", summary="Trigger a fresh prediction for one asset")
def trigger_single_asset(asset_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-runs the full PDM pipeline for a single asset and upserts the result.
    Returns the prediction summary."""
    from app.main import clf_model, clf_features, clf_threshold, clf_categorical_cols, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=503, detail="ML models are not loaded yet")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    result = run_batch_for_asset(
        db=db,
        asset=asset,
        clf_model=clf_model,
        clf_features=clf_features,
        clf_threshold=clf_threshold,
        clf_categorical_cols=clf_categorical_cols,
        reg_model=reg_model,
        reg_features=reg_features,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "Prediction failed"))

    # Return the freshly written row
    row = db.query(PdmBatchPrediction).filter(PdmBatchPrediction.asset_id == asset_id).first()
    return _serialize(row) if row else result
