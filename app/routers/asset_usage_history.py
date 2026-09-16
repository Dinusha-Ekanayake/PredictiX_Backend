"""Per-asset operating history endpoint.

GET /assets/{asset_id}/usage-history

Serves the asset section's utilisation and service-cadence charts from stored
sensor readings. No model is involved, so nothing here is a prediction.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, is_admin_role, require_user, assert_asset_in_scope
from app.models import Asset
from app.schemas.asset_usage_history import AssetUsageHistoryResponse, UsagePointOut
from app.services.asset_usage_history_service import (
    DEFAULT_MONTHS,
    MAX_MONTHS,
    get_asset_usage_history,
)

router = APIRouter(
    prefix="/assets",
    tags=["Asset Usage History"],
    dependencies=[Depends(require_user)],
)


@router.get("/{asset_id}/usage-history", response_model=AssetUsageHistoryResponse)
def get_usage_history(
    asset_id: UUID,
    months: int = Query(default=DEFAULT_MONTHS, ge=1, le=MAX_MONTHS),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Recorded monthly operation for one asset, oldest point first.

    Regular users may only read history for an asset assigned to them, and
    admins are scoped to their active warehouse, so neither can reach an
    asset they do not hold. An asset that exists but is out of the caller's
    scope answers 404 rather than 403, matching the other asset endpoints, so
    the response cannot be used to discover assets elsewhere in the fleet.

    An asset with no readings yet returns an empty ``points`` list.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    if is_admin_role(current_user):
        assert_asset_in_scope(asset, current_user)
    elif str(asset.assigned_to) != str(getattr(current_user, "id", "")):
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    points = get_asset_usage_history(db, str(asset_id), months=months)
    return AssetUsageHistoryResponse(
        asset_id=str(asset_id),
        months=months,
        points=[UsagePointOut(**vars(p)) for p in points],
    )
