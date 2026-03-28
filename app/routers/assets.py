from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Asset
from app.schemas.asset import AssetCreate, AssetUpdate, AssetOut

router = APIRouter(prefix="/assets", tags=["Assets"])


@router.post("/", response_model=AssetOut)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    existing_code = db.query(Asset).filter(Asset.asset_code == payload.asset_code).first()
    if existing_code:
        raise HTTPException(status_code=400, detail="Asset code already exists")

    if payload.vin:
        existing_vin = db.query(Asset).filter(Asset.vin == payload.vin).first()
        if existing_vin:
            raise HTTPException(status_code=400, detail="VIN already exists")

    obj = Asset(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetOut])
def list_assets(
    warehouse_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    vehicle_type: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Asset)

    if warehouse_id:
        q = q.filter(Asset.warehouse_id == warehouse_id)
    if department_id:
        q = q.filter(Asset.department_id == department_id)
    if status:
        q = q.filter(Asset.status == status)
    if assigned_to:
        q = q.filter(Asset.assigned_to == assigned_to)
    if vehicle_type:
        q = q.filter(Asset.vehicle_type == vehicle_type)
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type)
    if search:
        like_term = f"%{search}%"
        q = q.filter(
            (Asset.asset_name.ilike(like_term)) |
            (Asset.asset_code.ilike(like_term)) |
            (Asset.registration_number.ilike(like_term)) |
            (Asset.vin.ilike(like_term)) |
            (Asset.make.ilike(like_term)) |
            (Asset.model.ilike(like_term))
        )

    return (
        q.order_by(Asset.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/count")
def count_assets(
    warehouse_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Asset)

    if warehouse_id:
        q = q.filter(Asset.warehouse_id == warehouse_id)
    if status:
        q = q.filter(Asset.status == status)

    return {"count": q.count()}


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    return obj


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: str, payload: AssetUpdate, db: Session = Depends(get_db)):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")

    update_data = payload.model_dump(exclude_unset=True)

    if "vin" in update_data and update_data["vin"]:
        existing_vin = (
            db.query(Asset)
            .filter(Asset.vin == update_data["vin"], Asset.id != obj.id)
            .first()
        )
        if existing_vin:
            raise HTTPException(status_code=400, detail="VIN already exists")

    if "asset_code" in update_data and update_data["asset_code"]:
        existing_code = (
            db.query(Asset)
            .filter(Asset.asset_code == update_data["asset_code"], Asset.id != obj.id)
            .first()
        )
        if existing_code:
            raise HTTPException(status_code=400, detail="Asset code already exists")

    for key, value in update_data.items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{asset_id}/assign", response_model=AssetOut)
def assign_asset(asset_id: str, assigned_to: str | None, db: Session = Depends(get_db)):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj.assigned_to = assigned_to
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{asset_id}/status", response_model=AssetOut)
def update_asset_status(asset_id: str, status: str, db: Session = Depends(get_db)):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj.status = status
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")

    db.delete(obj)
    db.commit()
    return {"message": "Asset deleted successfully"}