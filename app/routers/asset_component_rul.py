"""Per-asset component RUL (Remaining Useful Life) endpoint.

GET /assets/{asset_id}/component-rul

Independent of /survival/{asset_id} (app/routers/survival_predictions.py),
which backs the warehouse report generation feature and is out of scope
here. This endpoint is asset-section only.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, is_admin_role, require_user, assert_asset_in_scope
from app.ai.services.asset_component_rul_service import compute_asset_component_rul
from app.models import Asset
from app.schemas.asset_component_rul import AssetComponentRulResponse, ComponentRulOut

router = APIRouter(
    prefix="/assets",
    tags=["Asset Component RUL"],
    dependencies=[Depends(require_user)],
)


@router.get("/{asset_id}/component-rul", response_model=AssetComponentRulResponse)
def get_asset_component_rul(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Per-component remaining-useful-life estimate for one asset, computed
    from that asset's own sensor_readings history (linear trend extrapolation
    to a component-specific health failure threshold).

    Regular users may only fetch RUL data for an asset assigned to them.
    Admins are scoped to their active warehouse — previously not checked
    at all here, so any admin could pull component-RUL estimates for an
    asset in a warehouse they don't manage.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    if is_admin_role(current_user):
        assert_asset_in_scope(asset, current_user)
    elif str(asset.assigned_to) != str(getattr(current_user, "id", "")):
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    try:
        components = compute_asset_component_rul(db, str(asset_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Component RUL estimation failed: {e}")

    return AssetComponentRulResponse(
        asset_id=str(asset_id),
        components=[ComponentRulOut(**vars(c)) for c in components],
    )
