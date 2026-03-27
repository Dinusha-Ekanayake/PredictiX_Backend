from fastapi import APIRouter, HTTPException
from app.repositories.vehicle_repository import (
    get_vehicle_by_id,
    get_latest_snapshot,
    save_prediction,
)
from app.ai.services.prediction_service import run_full_prediction

router = APIRouter(prefix="/vehicles", tags=["Vehicle Predictions"])


@router.post("/{vehicle_id}/predictions/full")
def predict_vehicle(vehicle_id: str):
    from app.main import clf_model, clf_features, reg_model, reg_features

    vehicle = get_vehicle_by_id(vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    snapshot = get_latest_snapshot(vehicle_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="No snapshot found for vehicle")

    payload = {**vehicle, **snapshot}

    result = run_full_prediction(
        data=payload,
        clf_model=clf_model,
        clf_features=clf_features,
        reg_model=reg_model,
        reg_features=reg_features,
    )

    save_prediction({
        "vehicle_id": vehicle_id,
        "snapshot_id": snapshot["id"],
        "maintenance_probability": result["maintenance_probability"],
        "maintenance_required_next_30d": bool(result["maintenance_required_next_30d"]),
        "predicted_days_until_maintenance": result["predicted_days_until_maintenance"],
        "predicted_maintenance_date": result["predicted_maintenance_date"],
        "health_score": result["health_score"],
        "health_status": result["health_status"],
        "risk_level": result["risk_level"],
        "recommended_action": result["recommended_action"],
        "regression_explanations": result["top_explanations"],
        "health_contributing_factors": result["contributing_factors"],
    })

    return result