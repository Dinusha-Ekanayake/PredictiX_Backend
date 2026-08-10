from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from app.deps import (
    get_db,
    get_current_user,
    is_admin_role,
    require_admin,
    require_user,
    assert_asset_in_scope,
    user_can_view_asset,
)
from app.models import Asset, AssetStatusHistory
from app.schemas.misc import AssetStatusHistoryCreate, AssetStatusHistoryOut

router = APIRouter(
    prefix="/asset-status-history",
    tags=["Asset Status History"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=AssetStatusHistoryOut, dependencies=[Depends(require_admin)])
def create_asset_status_history(payload: AssetStatusHistoryCreate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj = AssetStatusHistory(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetStatusHistoryOut])
def list_asset_status_history(
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # A specific asset_id is required so this can be scoped — without one,
    # an admin previously received the entire table across every warehouse
    # (the admin branch below never applied a filter), and even a "user"
    # role's own filter had no pagination cap. Same fix already applied to
    # the analogous ticket_status_history.py endpoint.
    if not asset_id:
        raise HTTPException(status_code=400, detail="asset_id is required")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if is_admin_role(current_user):
        assert_asset_in_scope(asset, current_user)
    elif not user_can_view_asset(asset, current_user):
        raise HTTPException(status_code=404, detail="Asset not found")

    return (
        db.query(AssetStatusHistory)
        .filter(AssetStatusHistory.asset_id == asset_id)
        .order_by(AssetStatusHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )