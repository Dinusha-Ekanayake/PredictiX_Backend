"""
FRSO survival prediction endpoints.

GET  /survival/{asset_id}/{component}    — single-component survival curve + RUL
GET  /survival/{asset_id}                — all 5 components for one asset
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.ai.services import survival_service
from app.schemas.survival import (
    AssetSurvivalResponse,
    ComponentSurvivalResponse,
    FleetSurvivalSummary,
)


router = APIRouter(prefix="/survival", tags=["FRSO Survival"])


# NOTE: this static route must be declared BEFORE the /{asset_id} routes below,
# otherwise "warehouse" would be captured as an asset_id.
@router.get("/warehouse/summary", response_model=FleetSurvivalSummary)
def get_fleet_survival_summary(
    max_assets:   int = Query(12,  ge=1,  le=50),
    horizon_days: int = Query(180, ge=14, le=720),
    db: Session = Depends(get_db),
):
    """Fleet-level survival summary over the warehouse's most at-risk assets:
    per-component RUL stats + a soonest-failing watchlist."""
    try:
        return survival_service.fleet_survival_summary(
            db=db,
            max_assets=max_assets,
            horizon_days=horizon_days,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fleet survival summary failed: {e}")


@router.get("/{asset_id}/{component}", response_model=ComponentSurvivalResponse)
def get_component_survival(
    asset_id: str,
    component: str,
    horizon_days: int = Query(180, ge=14, le=720),
    step_days:    int = Query(7,   ge=1,  le=30),
    db: Session = Depends(get_db),
):
    """Predict the survival curve for one component of one asset."""
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
):
    """Predict survival curves for all 5 components of one asset."""
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
