"""Per-asset component RUL (Remaining Useful Life) endpoint.

GET /assets/{asset_id}/component-rul

Independent of /survival/{asset_id} (app/routers/survival_predictions.py),
which backs the warehouse report generation feature and is out of scope
here. This endpoint is asset-section only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, require_user
from app.ai.services.asset_component_rul_service import compute_asset_component_rul
from app.schemas.asset_component_rul import AssetComponentRulResponse, ComponentRulOut

router = APIRouter(
    prefix="/assets",
    tags=["Asset Component RUL"],
    dependencies=[Depends(require_user)],
)


@router.get("/{asset_id}/component-rul", response_model=AssetComponentRulResponse)
def get_asset_component_rul(asset_id: str, db: Session = Depends(get_db)):
    """Per-component remaining-useful-life estimate for one asset, computed
    from that asset's own sensor_readings history (linear trend extrapolation
    to a 20% health failure threshold)."""
    try:
        components = compute_asset_component_rul(db, asset_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Component RUL estimation failed: {e}")

    return AssetComponentRulResponse(
        asset_id=asset_id,
        components=[ComponentRulOut(**vars(c)) for c in components],
    )
