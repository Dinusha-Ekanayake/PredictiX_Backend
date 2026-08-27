"""Single-asset, on-demand PDM prediction ("/vehicle-predictions/{asset_id}").

Historically this ran its own separate copy of the classifier/regressor
inference logic against ``asset_failure_predictions`` /
``asset_cost_predictions``, a second pipeline alongside the scheduled batch
job, using different feature-building code that could (and did) drift out of
sync with it. It now delegates to
``app.ai.services.batch_prediction_service.run_batch_for_asset``, the exact
same feature builder, v7 LightGBM models, and decision layer used by the
daily scheduler, so an on-demand "refresh this asset now" always agrees
with what the next scheduled run would have produced, and both write to the
single source of truth, ``pdm_batch_predictions``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Asset, SensorReading
from app.ai.services.batch_prediction_service import run_batch_for_asset


# Kept here (rather than moved) because app.ai.services.survival_service
# imports these four generic helpers, unrelated to which PdM model
# generation is loaded, so they don't need to change with the v7 swap.
def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _get_asset(db: Session, asset_id: str):
    return db.query(Asset).filter(Asset.id == asset_id).first()


def _get_latest_sensor_reading(db: Session, asset_id: str):
    return (
        db.query(SensorReading)
        .filter(SensorReading.asset_id == asset_id)
        .order_by(SensorReading.recorded_at.desc())
        .first()
    )


def run_vehicle_prediction_and_store(
    db: Session,
    asset_id: str,
    requested_by: str | None,
    clf_model,
    clf_features: list[str],
    reg_model,
    reg_features: list[str],
) -> dict[str, Any]:
    from app.main import clf_threshold, clf_categorical_cols, reg_categorical_cols

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise ValueError("Asset not found")

    result = run_batch_for_asset(
        db=db,
        asset=asset,
        clf_model=clf_model,
        clf_features=clf_features,
        clf_threshold=clf_threshold,
        clf_categorical_cols=clf_categorical_cols,
        reg_model=reg_model,
        reg_features=reg_features,
        reg_categorical_cols=reg_categorical_cols,
    )

    if result.get("status") == "no_data":
        raise ValueError("No sensor reading found for asset")
    if result.get("status") == "error":
        raise ValueError(result.get("error", "Prediction failed"))

    return result
