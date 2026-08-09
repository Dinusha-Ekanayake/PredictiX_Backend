"""
FRSO survival prediction endpoints.

GET  /survival/{asset_id}/{component}    — single-component survival curve + RUL
GET  /survival/{asset_id}                — all 5 components for one asset
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, require_user, assert_asset_in_scope
from app.models import Asset, Profile
from app.ai.services import survival_service
from app.schemas.survival import (
    AssetSurvivalResponse,
    ComponentSurvivalResponse,
)


router = APIRouter(
    prefix="/survival",
    tags=["FRSO Survival"],
    dependencies=[Depends(require_user)],
)


@router.get("/{asset_id}/{component}", response_model=ComponentSurvivalResponse)
def get_component_survival(
    asset_id: str,
    component: str,
    horizon_days: int = Query(180, ge=14, le=720),
    step_days:    int = Query(7,   ge=1,  le=30),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Predict the survival curve for one component of one asset."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)
    try:
        return survival_service.predict_survival_curve(
            db=db,
            asset_id=asset_id,
            component=component,
            horizon_days=horizon_days,
            step_days=step_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Survival prediction failed: {e}")


@router.get("/{asset_id}", response_model=AssetSurvivalResponse)
def get_asset_survival(
    asset_id: str,
    horizon_days: int = Query(180, ge=14, le=720),
    step_days:    int = Query(14,  ge=1,  le=30),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Predict survival curves for all 5 components of one asset."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)
    try:
        return survival_service.predict_all_components(
            db=db,
            asset_id=asset_id,
            horizon_days=horizon_days,
            step_days=step_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Survival prediction failed: {e}")
