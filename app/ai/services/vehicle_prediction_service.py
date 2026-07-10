"""Single-asset, on-demand PDM prediction ("/vehicle-predictions/{asset_id}").

Historically this ran its own separate copy of the classifier/regressor
inference logic against ``asset_failure_predictions`` /
``asset_cost_predictions`` — a second pipeline alongside the scheduled batch
job, using different feature-building code that could (and did) drift out of
sync with it. It now delegates to
``app.ai.services.batch_prediction_service.run_batch_for_asset`` — the exact
same feature builder, v7 LightGBM models, and decision layer used by the
daily scheduler — so an on-demand "refresh this asset now" always agrees
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
# imports these four generic helpers — unrelated to which PdM model
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

<<<<<<< HEAD
    feature_dict = build_vehicle_feature_dict(db, asset_id)

    clf_df = build_dataframe_for_features(feature_dict, clf_features)
    reg_df = build_dataframe_for_features(feature_dict, reg_features)

    try:
        predicted_class = int(clf_model.predict(clf_df)[0])
        if hasattr(clf_model, "predict_proba"):
            probas = clf_model.predict_proba(clf_df)[0]
            failure_probability = float(probas[-1]) if len(probas) > 1 else float(probas[0])
            confidence = float(max(probas))
        else:
            failure_probability = float(predicted_class)
            confidence = 0.75
    except Exception as e:
        import logging
        logging.getLogger("predictix.ai").warning(f"Classifier failed: {e}. Falling back to 0.05.")
        predicted_class = 0
        failure_probability = 0.05
        confidence = 0.75

    # regressor — CatBoost requires a Pool with cat_features for string columns
    try:
        from catboost import Pool as CatPool
        _reg_cat_indices: list[int] = []
        try:
            _reg_cat_indices = [
                reg_df.columns.get_loc(reg_df.columns[i])
                for i in reg_model.get_cat_feature_indices()
                if i < len(reg_df.columns)
            ]
            # CatBoost Pool requires string values for categorical columns
            for idx in _reg_cat_indices:
                col = reg_df.columns[idx]
                reg_df[col] = reg_df[col].astype(str)
        except Exception:
            pass
        reg_pool = CatPool(reg_df, cat_features=_reg_cat_indices)
        predicted_days_until = float(reg_model.predict(reg_pool)[0])
    except Exception:
        predicted_days_until = float(reg_model.predict(reg_df)[0])
    predicted_days_until = max(0.0, round(predicted_days_until, 2))

    predicted_maintenance_date = date.today() + timedelta(days=int(round(predicted_days_until)))
    health_score, health_band = compute_health_score(feature_dict, failure_probability, predicted_days_until)
    risk_level = compute_risk_level(failure_probability, predicted_days_until)
    estimated_cost, min_cost, max_cost = estimate_cost(feature_dict, failure_probability, predicted_days_until)

    clf_registry = _get_model_registry(db, CLASSIFIER_MODEL_NAME)
    if not clf_registry:
        raise ValueError(f"Model registry entry not found for {CLASSIFIER_MODEL_NAME}")

    run = PredictionRun(
        id=uuid.uuid4(),
        model_id=clf_registry.id,
        asset_id=asset.id,
        ticket_id=None,
        input_snapshot=feature_dict,
        requested_by=requested_by,
        run_started_at=datetime.utcnow(),
        run_finished_at=datetime.utcnow(),
        status="completed",
        error_message=None,
=======
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
>>>>>>> 35e3ac103591052fc88dd59200e314bb3792f95b
    )

    if result.get("status") == "no_data":
        raise ValueError("No sensor reading found for asset")
    if result.get("status") == "error":
        raise ValueError(result.get("error", "Prediction failed"))

    return result
