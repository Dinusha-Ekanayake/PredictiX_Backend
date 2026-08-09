from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, require_user, assert_asset_in_scope
from app.models import Asset, Profile
from app.ai.services.vehicle_prediction_service import run_vehicle_prediction_and_store

router = APIRouter(
    prefix="/vehicle-predictions",
    tags=["Vehicle Predictions"],
    dependencies=[Depends(require_user)],
)


@router.post("/{asset_id}")
def predict_vehicle(
    asset_id: str,
    requested_by: str | None = None,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    from app.main import clf_model, clf_features, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=500, detail="Models are not loaded")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

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