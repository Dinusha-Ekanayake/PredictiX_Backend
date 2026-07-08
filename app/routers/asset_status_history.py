from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user
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
    db: Session = Depends(get_db),
):
    q = db.query(AssetStatusHistory)
    if asset_id:
        q = q.filter(AssetStatusHistory.asset_id == asset_id)
    return q.order_by(AssetStatusHistory.created_at.desc()).all()