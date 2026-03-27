from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import AssetStatusHistory
from app.schemas.misc import AssetStatusHistoryCreate, AssetStatusHistoryOut

router = APIRouter(prefix="/asset-status-history", tags=["Asset Status History"])


@router.post("/", response_model=AssetStatusHistoryOut)
def create_asset_status_history(payload: AssetStatusHistoryCreate, db: Session = Depends(get_db)):
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