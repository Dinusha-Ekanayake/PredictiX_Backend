from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.deps import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetUpdate, AssetOut, AssetListOut

router = APIRouter(prefix="/assets", tags=["Assets"])


# --------- Simple role guard (works if your auth already attaches role in request) ---------
# If you already have get_current_user() in your project, replace this with your own.
def require_admin(role: str = "USER"):
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")


# TODO: Replace this with your real auth dependency that returns current user info.
# For now, it reads role from query param to avoid blocking you.
def get_role(role: str = Query("USER")):
    return role


@router.get("", response_model=AssetListOut)
def list_assets(
    db: Session = Depends(get_db),
    status: str | None = None,
    category_id: int | None = None,
    location: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    query = db.query(Asset)

    if status:
        query = query.filter(Asset.status == status)
    if category_id:
        query = query.filter(Asset.category_id == category_id)
    if location:
        query = query.filter(Asset.location.ilike(f"%{location}%"))
    if q:
        query = query.filter(
            (Asset.name.ilike(f"%{q}%")) |
            (Asset.asset_code.ilike(f"%{q}%"))
        )

    total = query.with_entities(func.count()).scalar() or 0
    items = (
        query.order_by(Asset.asset_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # convert metadata_ -> metadata in response
    out_items = []
    for a in items:
        out_items.append(
            AssetOut(
                asset_id=a.asset_id,
                asset_code=a.asset_code,
                name=a.name,
                description=a.description,
                category_id=a.category_id,
                location=a.location,
                asset_family=a.asset_family,
                status=a.status,
                criticality=a.criticality,
                installation_date=a.installation_date,
                health_score=a.health_score,
                metadata=a.metadata_ or {},
                created_at=a.created_at,
            )
        )

    return AssetListOut(items=out_items, total=total, page=page, page_size=page_size)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetOut(
        asset_id=asset.asset_id,
        asset_code=asset.asset_code,
        name=asset.name,
        description=asset.description,
        category_id=asset.category_id,
        location=asset.location,
        asset_family=asset.asset_family,
        status=asset.status,
        criticality=asset.criticality,
        installation_date=asset.installation_date,
        health_score=asset.health_score,
        metadata=asset.metadata_ or {},
        created_at=asset.created_at,
    )


@router.post("", response_model=AssetOut)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),  # replace later with real auth
):
    require_admin(role)

    exists = db.query(Asset).filter(Asset.asset_code == payload.asset_code).first()
    if exists:
        raise HTTPException(status_code=409, detail="asset_code already exists")

    asset = Asset(
        asset_code=payload.asset_code,
        name=payload.name,
        description=payload.description,
        category_id=payload.category_id,
        location=payload.location,
        asset_family=payload.asset_family,
        status=payload.status,
        criticality=payload.criticality,
        installation_date=payload.installation_date,
        health_score=payload.health_score,
        metadata_=payload.metadata,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    return AssetOut(
        asset_id=asset.asset_id,
        asset_code=asset.asset_code,
        name=asset.name,
        description=asset.description,
        category_id=asset.category_id,
        location=asset.location,
        asset_family=asset.asset_family,
        status=asset.status,
        criticality=asset.criticality,
        installation_date=asset.installation_date,
        health_score=asset.health_score,
        metadata=asset.metadata_ or {},
        created_at=asset.created_at,
    )


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),  # replace later with real auth
):
    require_admin(role)

    asset = db.query(Asset).filter(Asset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    data = payload.model_dump(exclude_unset=True)

    # map schema "metadata" to model attribute "metadata_"
    if "metadata" in data:
        asset.metadata_ = data.pop("metadata") if data["metadata"] is not None else asset.metadata_

    for key, value in data.items():
        setattr(asset, key, value)

    db.commit()
    db.refresh(asset)

    return AssetOut(
        asset_id=asset.asset_id,
        asset_code=asset.asset_code,
        name=asset.name,
        description=asset.description,
        category_id=asset.category_id,
        location=asset.location,
        asset_family=asset.asset_family,
        status=asset.status,
        criticality=asset.criticality,
        installation_date=asset.installation_date,
        health_score=asset.health_score,
        metadata=asset.metadata_ or {},
        created_at=asset.created_at,
    )


@router.delete("/{asset_id}")
def retire_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),  # replace later with real auth
):
    require_admin(role)

    asset = db.query(Asset).filter(Asset.asset_id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.status = "RETIRED"
    db.commit()

    return {"success": True, "message": "Asset retired"}
