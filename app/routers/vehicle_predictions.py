from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.ai.services.vehicle_prediction_service import run_vehicle_prediction_and_store

router = APIRouter(prefix="/vehicle-predictions", tags=["Vehicle Predictions"])

from app.schemas.prediction import VehiclePredictionStoredResponse

@router.post("/{asset_id}")
def predict_vehicle(asset_id: str, requested_by: str | None = None, db: Session = Depends(get_db)):
    from app.main import _load_pdm_models
    _load_pdm_models()
    from app.main import clf_model, clf_features, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=500, detail="Models are not loaded")

    try:
        result = run_vehicle_prediction_and_store(
            db=db,
            asset_id=asset_id,
            requested_by=requested_by,
            clf_model=clf_model,
            clf_features=clf_features,
            reg_model=reg_model,
            reg_features=reg_features,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vehicle prediction failed: {str(e)}")