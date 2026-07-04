"""Assets resource — CRUD, search, assignment, status updates."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, or_, func, case
from sqlalchemy.orm import Session

from app.deps import (
    get_db,
    get_current_user,
    require_user,
    require_admin,
    active_warehouse_id,
    is_admin_role,
    _role_of,
    ADMIN_ROLES,
)
from app.models import Asset, Profile
from app.schemas.asset import AssetCreate, AssetOut, AssetListOut, AssetUpdate
from app.services.service_reminder_service import send_manual_reminder


def _enforced_warehouse(current_user) -> str | None:
    """Warehouse an admin/super_admin request must be scoped to.

    Admins and super_admins both operate inside exactly one active warehouse
    (a super_admin's is the one they picked at login). Returns that warehouse id
    for admin roles, or None for non-admin callers / when no warehouse is set
    (in which case no extra scoping is applied here).
    """
    if _role_of(current_user) in ADMIN_ROLES:
        return active_warehouse_id(current_user)
    return None


def _assert_asset_in_scope(obj: Asset, current_user) -> None:
    """Block admins/super_admins from touching an asset outside their active
    warehouse. Returns 404 (not 403) so the asset's existence isn't revealed
    across warehouse boundaries."""
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh and str(obj.warehouse_id) != scoped_wh:
        raise HTTPException(status_code=404, detail="Asset not found")

# require_user gates every endpoint (valid token needed); mutating endpoints
# additionally require_admin below.
router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
    dependencies=[Depends(require_user)],
)


class ServiceReminderRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


@router.get("/dropdown", summary="Lightweight asset list for dropdowns")
def list_assets_dropdown(
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Returns only id, asset_code, asset_name, asset_type, warehouse_id — fast for populating dropdowns."""
    q = db.query(Asset.id, Asset.asset_code, Asset.asset_name, Asset.asset_type, Asset.warehouse_id)
    # Scope admins/super_admins to their active warehouse.
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        q = q.filter(Asset.warehouse_id == scoped_wh)
    if search:
        like_term = f"%{search.strip()}%"
        q = q.filter(or_(
            Asset.asset_name.ilike(like_term),
            Asset.asset_code.ilike(like_term),
        ))
    if status:
        q = q.filter(Asset.status == status)
    rows = q.order_by(Asset.asset_name.asc()).all()
    return [
        {
            "id": str(r.id),
            "asset_code": r.asset_code,
            "asset_name": r.asset_name,
            "asset_type": r.asset_type,
            "warehouse_id": str(r.warehouse_id),
        }
        for r in rows
    ]


@router.post("/", response_model=AssetOut, dependencies=[Depends(require_admin)])
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    existing_code = db.query(Asset).filter(Asset.asset_code == payload.asset_code).first()
    if existing_code:
        raise HTTPException(status_code=400, detail="Asset code already exists")

    if payload.vin:
        existing_vin = db.query(Asset).filter(Asset.vin == payload.vin).first()
        if existing_vin:
            raise HTTPException(status_code=400, detail="VIN already exists")

    data = payload.model_dump()
    # Pin the new asset to the admin's active warehouse so an admin can't create
    # assets in another warehouse. A super_admin's active warehouse is the one
    # they picked at login.
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        data["warehouse_id"] = scoped_wh

    obj = Asset(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetListOut])
def list_assets(
    search: str | None = Query(default=None, description="Search by asset id, asset code, asset name, VIN, registration, make, model"),
    warehouse_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    vehicle_type: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    vehicle_role: str | None = Query(default=None),
    make: str | None = Query(default=None),
    model: str | None = Query(default=None),
    manufacture_year: int | None = Query(default=None),
    health_band: str | None = Query(default=None),
    min_criticality_score: float | None = Query(default=None),
    max_criticality_score: float | None = Query(default=None),
    min_current_mileage: float | None = Query(default=None),
    max_current_mileage: float | None = Query(default=None),
    min_payload_capacity_kg: float | None = Query(default=None),
    max_payload_capacity_kg: float | None = Query(default=None),
    is_assigned: bool | None = Query(default=None, description="true = assigned, false = unassigned"),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(Asset)

    # Warehouse scoping: admins/super_admins are pinned to their active
    # warehouse. Any client-supplied warehouse_id is overridden so it can't be
    # used to read another warehouse's assets.
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        warehouse_id = scoped_wh

    if search:
        like_term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                cast(Asset.id, String).ilike(like_term),
                Asset.asset_code.ilike(like_term),
                Asset.asset_name.ilike(like_term),
                Asset.registration_number.ilike(like_term),
                Asset.vin.ilike(like_term),
                Asset.make.ilike(like_term),
                Asset.model.ilike(like_term),
            )
        )

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
    if vehicle_role:
        q = q.filter(Asset.vehicle_role == vehicle_role)
    if make:
        q = q.filter(Asset.make.ilike(f"%{make.strip()}%"))
    if model:
        q = q.filter(Asset.model.ilike(f"%{model.strip()}%"))
    if manufacture_year is not None:
        q = q.filter(Asset.manufacture_year == manufacture_year)
    if health_band:
        q = q.filter(Asset.health_band == health_band)

    if is_assigned is True:
        q = q.filter(Asset.assigned_to.isnot(None))
    elif is_assigned is False:
        q = q.filter(Asset.assigned_to.is_(None))

    if min_criticality_score is not None:
        q = q.filter(Asset.criticality_score >= min_criticality_score)
    if max_criticality_score is not None:
        q = q.filter(Asset.criticality_score <= max_criticality_score)

    if min_current_mileage is not None:
        q = q.filter(Asset.current_mileage >= min_current_mileage)
    if max_current_mileage is not None:
        q = q.filter(Asset.current_mileage <= max_current_mileage)

    if min_payload_capacity_kg is not None:
        q = q.filter(Asset.payload_capacity_kg >= min_payload_capacity_kg)
    if max_payload_capacity_kg is not None:
        q = q.filter(Asset.payload_capacity_kg <= max_payload_capacity_kg)

    sort_column_map = {
        "created_at": Asset.created_at,
        "updated_at": Asset.updated_at,
        "asset_name": Asset.asset_name,
        "asset_code": Asset.asset_code,
        "status": Asset.status,
        "vehicle_type": Asset.vehicle_type,
        "make": Asset.make,
        "model": Asset.model,
        "manufacture_year": Asset.manufacture_year,
        "current_mileage": Asset.current_mileage,
        "criticality_score": Asset.criticality_score,
        "payload_capacity_kg": Asset.payload_capacity_kg,
    }

    sort_column = sort_column_map.get(sort_by, Asset.created_at)
    if sort_order.lower() == "asc":
        q = q.order_by(sort_column.asc())
    else:
        q = q.order_by(sort_column.desc())

    # Project down to only the columns the list view needs (AssetListOut) —
    # filters/sort above still run against the full table; this only trims
    # what's SELECTed and hydrated into Python, cutting payload + ORM overhead.
    q = q.with_entities(
        Asset.id,
        Asset.asset_code,
        Asset.asset_name,
        Asset.asset_type,
        Asset.vehicle_type,
        Asset.make,
        Asset.model,
        Asset.manufacture_year,
        Asset.status,
        Asset.health_band,
        Asset.warehouse_id,
        Asset.meta,
    )

    return q.offset(offset).limit(limit).all()


@router.get("/count")
def count_assets(
    search: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: str | None = Query(default=None),
    vehicle_type: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    vehicle_role: str | None = Query(default=None),
    is_assigned: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(Asset)

    # Warehouse scoping (see list_assets): pin admins to their active warehouse.
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        warehouse_id = scoped_wh

    if search:
        like_term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                cast(Asset.id, String).ilike(like_term),
                Asset.asset_code.ilike(like_term),
                Asset.asset_name.ilike(like_term),
                Asset.registration_number.ilike(like_term),
                Asset.vin.ilike(like_term),
                Asset.make.ilike(like_term),
                Asset.model.ilike(like_term),
            )
        )

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
    if vehicle_role:
        q = q.filter(Asset.vehicle_role == vehicle_role)

    if is_assigned is True:
        q = q.filter(Asset.assigned_to.isnot(None))
    elif is_assigned is False:
        q = q.filter(Asset.assigned_to.is_(None))

    return {"count": q.count()}


@router.get("/stats")
def get_asset_stats(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Fleet-wide asset summary counts for the AssetsSummary cards.

    Computed as SQL aggregates over ALL matching assets (scoped to the
    caller's warehouse the same way list_assets is), independent of whatever
    page of results the table is currently showing. This exists so paginating
    the list endpoint doesn't change what the summary cards report.
    """
    q = db.query(Asset)
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        q = q.filter(Asset.warehouse_id == scoped_wh)

    band_score = case(
        (Asset.health_band == "excellent", 90),
        (Asset.health_band == "good", 72),
        (Asset.health_band == "moderate", 52),
        (Asset.health_band == "poor", 30),
        (Asset.health_band == "critical", 12),
        else_=50,
    )

    # Real values of the asset_status Postgres enum: active, inactive,
    # under_maintenance, critical, decommissioned.
    row = q.with_entities(
        func.count(Asset.id),
        func.count(Asset.id).filter(cast(Asset.status, String) == "active"),
        func.count(Asset.id).filter(cast(Asset.status, String) == "under_maintenance"),
        func.count(Asset.id).filter(Asset.health_band == "critical"),
        func.count(Asset.id).filter(cast(Asset.status, String).in_(("inactive", "decommissioned"))),
        func.avg(band_score),
    ).one()

    total, operational, maintenance, critical, offline, avg_band_score = row
    total = int(total or 0)

    return {
        "total": total,
        "operational": int(operational or 0),
        "maintenance": int(maintenance or 0),
        "critical": int(critical or 0),
        "offline": int(offline or 0),
        "avgHealth": round(float(avg_band_score), 0) if total and avg_band_score is not None else 0,
    }


@router.get("/analytics")
def get_asset_analytics(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Fleet-wide descriptive analytics for the AssetsAnalytics charts:
    status distribution, health-band distribution, vehicle-type breakdown,
    and the top 5 at-risk assets. Computed over ALL matching assets (scoped
    to the caller's warehouse), independent of pagination — so the charts
    don't silently reflect only whatever page of the table is showing.
    """
    base_q = db.query(Asset)
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        base_q = base_q.filter(Asset.warehouse_id == scoped_wh)

    status_rows = (
        base_q.with_entities(cast(Asset.status, String), func.count(Asset.id))
        .group_by(Asset.status)
        .all()
    )
    health_rows = (
        base_q.with_entities(Asset.health_band, func.count(Asset.id))
        .group_by(Asset.health_band)
        .all()
    )
    type_rows = (
        base_q.with_entities(
            func.coalesce(Asset.vehicle_type, Asset.asset_type, "Other"),
            func.count(Asset.id),
        )
        .group_by(func.coalesce(Asset.vehicle_type, Asset.asset_type, "Other"))
        .order_by(func.count(Asset.id).desc())
        .limit(8)
        .all()
    )

    # Top 5 at-risk: critical first, then poor, each ordered by criticality_score desc.
    risk_order = case(
        (Asset.health_band == "critical", 0),
        (Asset.health_band == "poor", 1),
        else_=2,
    )
    at_risk_rows = (
        base_q.filter(Asset.health_band.in_(("critical", "poor")))
        .with_entities(Asset.id, Asset.asset_name, Asset.asset_code, Asset.health_band)
        .order_by(risk_order, Asset.criticality_score.desc().nullslast())
        .limit(5)
        .all()
    )

    return {
        "statusDistribution": [
            {"name": s or "unknown", "value": int(c)} for s, c in status_rows
        ],
        "healthDistribution": [
            {"name": (h or "unknown").lower(), "value": int(c)} for h, c in health_rows
        ],
        "vehicleTypeDistribution": [
            {"name": t or "Other", "value": int(c)} for t, c in type_rows
        ],
        "topAtRisk": [
            {
                "id": str(i),
                "asset_name": name,
                "asset_code": code,
                "health_band": band,
            }
            for i, name, code, band in at_risk_rows
        ],
    }


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)
    return obj


@router.put("/{asset_id}", response_model=AssetOut, dependencies=[Depends(require_admin)])
def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

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


@router.patch("/{asset_id}/assign", response_model=AssetOut, dependencies=[Depends(require_admin)])
def assign_asset(
    asset_id: str,
    assigned_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    obj.assigned_to = assigned_to
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{asset_id}/status", response_model=AssetOut, dependencies=[Depends(require_admin)])
def update_asset_status(
    asset_id: str,
    status: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    obj.status = status
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{asset_id}", dependencies=[Depends(require_admin)])
def delete_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    db.delete(obj)
    db.commit()
    return {"message": "Asset deleted successfully"}


@router.post(
    "/{asset_id}/send-service-reminder",
    summary="Send a service reminder email to the assigned user (admin only)",
)
def send_service_reminder_endpoint(
    asset_id: str,
    payload: ServiceReminderRequest | None = None,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Admin-triggered manual send with optional note included in the email."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admins only")

    try:
        asset_uuid = UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset id")

    note = payload.note.strip() if payload and payload.note else None

    try:
        result = send_manual_reminder(
            db,
            asset_id=asset_uuid,
            sent_by=current_user.id,
            admin_note=note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not result["sent"]:
        raise HTTPException(
            status_code=502,
            detail=result.get("error") or "Email send failed",
        )

    return result