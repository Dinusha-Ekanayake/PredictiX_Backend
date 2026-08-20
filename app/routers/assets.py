"""Assets resource, CRUD, search, assignment, status updates."""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, or_, func, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import (
    get_db,
    get_current_user,
    require_user,
    require_admin,
    active_warehouse_id,
    is_admin_role,
    is_super_admin,
    user_can_view_asset,
    _role_of,
    ADMIN_ROLES,
)
from app.models import (
    Asset,
    AssetAssignment,
    AssetCostPrediction,
    AssetDocument,
    AssetFailurePrediction,
    AssetStatusHistory,
    Department,
    MaintenanceEvent,
    Notification,
    PdmBatchPrediction,
    PredictionExplanation,
    PredictionRun,
    Profile,
    Report,
    SensorReading,
    Ticket,
)
from app.schemas.asset import AssetCreate, AssetOut, AssetListOut, AssetUpdate
from app.services.service_reminder_service import send_manual_reminder

# Real values of the assets.status Postgres enum.
_VALID_ASSET_STATUSES = {"active", "inactive", "under_maintenance", "critical", "decommissioned"}


def _purge_asset(db: Session, asset_id: str) -> None:
    """Delete an asset's owned child rows and null out soft references,
    then the asset itself, mirrors tickets.py's _purge_ticket.

    Without this, deleting any asset with real history (a sensor reading,
    an assignment, a status change, i.e. almost any real asset) raised an
    uncaught IntegrityError, since none of these child tables declare
    ondelete=CASCADE. PdmBatchPrediction/PdmPredictionHistory/
    ServiceReminderLog already cascade at the DB level and need no manual
    handling here.
    """
    # Owned child rows, deleted outright.
    db.query(MaintenanceEvent).filter(MaintenanceEvent.asset_id == asset_id).delete(synchronize_session=False)
    db.query(SensorReading).filter(SensorReading.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetAssignment).filter(AssetAssignment.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetStatusHistory).filter(AssetStatusHistory.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetDocument).filter(AssetDocument.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetFailurePrediction).filter(AssetFailurePrediction.asset_id == asset_id).delete(synchronize_session=False)
    db.query(AssetCostPrediction).filter(AssetCostPrediction.asset_id == asset_id).delete(synchronize_session=False)

    # Soft references, nulled out, the referencing record itself survives.
    db.query(PredictionExplanation).filter(PredictionExplanation.asset_id == asset_id).update(
        {PredictionExplanation.asset_id: None}, synchronize_session=False
    )
    db.query(Ticket).filter(Ticket.asset_id == asset_id).update(
        {Ticket.asset_id: None}, synchronize_session=False
    )
    db.query(PredictionRun).filter(PredictionRun.asset_id == asset_id).update(
        {PredictionRun.asset_id: None}, synchronize_session=False
    )
    db.query(Report).filter(Report.asset_id == asset_id).update(
        {Report.asset_id: None}, synchronize_session=False
    )
    db.query(Notification).filter(Notification.related_asset_id == asset_id).update(
        {Notification.related_asset_id: None}, synchronize_session=False
    )

    db.query(Asset).filter(Asset.id == asset_id).delete(synchronize_session=False)


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


def _non_admin_visibility_filter(current_user):
    """SQLAlchemy filter for a non-admin ("user" role) caller's asset
    visibility: their own warehouse, plus any asset specifically assigned
    to them even outside it, the same warehouse-wide rule already
    established for tickets (tickets.py's list_tickets/get_ticket).

    _enforced_warehouse() only ever scopes admin roles (returns None for
    "user"), and every read endpoint below only narrowed its query when
    that value was non-None, so a plain "user" account got zero warehouse
    scoping at all, wider access than a warehouse-pinned admin.
    """
    uid = str(getattr(current_user, "id", ""))
    user_wh_id = getattr(current_user, "warehouse_id", None)
    if user_wh_id:
        return or_(Asset.warehouse_id == user_wh_id, Asset.assigned_to == uid)
    return Asset.assigned_to == uid

# require_user gates every endpoint (valid token needed); mutating endpoints
# additionally require_admin below.
log = logging.getLogger(__name__)

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
    limit: int = Query(default=2000, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Returns only id, asset_code, asset_name, asset_type, warehouse_id, fast for populating dropdowns.

    The result is bounded. Both callers (the admin and user New Ticket dialogs)
    fetch this once on mount with no search term and filter client-side, so the
    bound must stay above the real fleet size or assets would silently vanish
    from the picker, the default of 2000 is well clear of the current ~850 and
    exists to stop the response growing without limit as the fleet does. The
    ``search`` parameter is already server-side, so the path to a smaller
    payload is to send it rather than to lower this number.
    """
    q = db.query(Asset.id, Asset.asset_code, Asset.asset_name, Asset.asset_type, Asset.warehouse_id)
    if is_admin_role(current_user):
        scoped_wh = _enforced_warehouse(current_user)
        if scoped_wh:
            q = q.filter(Asset.warehouse_id == scoped_wh)
    else:
        q = q.filter(_non_admin_visibility_filter(current_user))
    if search:
        like_term = f"%{search.strip()}%"
        q = q.filter(or_(
            Asset.asset_name.ilike(like_term),
            Asset.asset_code.ilike(like_term),
        ))
    if status:
        q = q.filter(Asset.status == status)
    rows = q.order_by(Asset.asset_name.asc()).limit(limit).all()
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

    # Checked up front like warehouse_id/vin/asset_code above. Left to the
    # database, a nonexistent department_id surfaces as an uncaught
    # IntegrityError (ForeignKeyViolation) on commit, a raw 500 where the
    # caller should get a clean 404.
    if payload.department_id:
        existing_dept = db.query(Department).filter(Department.id == payload.department_id).first()
        if not existing_dept:
            raise HTTPException(status_code=404, detail="Department not found")

    data = payload.model_dump()
    # Pin the new asset to the admin's active warehouse so an admin can't create
    # assets in another warehouse. A super_admin's active warehouse is the one
    # they picked at login.
    scoped_wh = _enforced_warehouse(current_user)
    if scoped_wh:
        data["warehouse_id"] = scoped_wh

    # created_by comes from the authenticated session, never the request
    # body, otherwise any admin could attribute a new asset to a different
    # real profile. Per AssetUpdate it can never be changed after this.
    data["created_by"] = current_user.id

    obj = Asset(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetListOut])
def list_assets(
    search: str | None = Query(default=None, description="Search by asset id, asset code, asset name, VIN, registration, make, model"),
    # UUID-typed (not str) so FastAPI/Pydantic reject a malformed value with a
    # clean 422 before it ever reaches the query. As raw strings these reach
    # Postgres directly and raise an uncaught 500 (InvalidTextRepresentation)
    # on anything that is not a real UUID.
    warehouse_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: UUID | None = Query(default=None),
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

    # Warehouse scoping. Admins/super_admins are pinned to their active
    # warehouse, any client-supplied warehouse_id is overridden so it can't
    # be used to read another warehouse's assets. Non-admin "user" accounts
    # get the same warehouse-wide visibility used everywhere else in the
    # app (tickets, comments): their own warehouse, plus anything assigned
    # to them. Without that scoping a "user" caller who simply omits
    # warehouse_id reads the entire fleet across every warehouse, broader
    # access than a scoped admin.
    if is_admin_role(current_user):
        scoped_wh = _enforced_warehouse(current_user)
        if scoped_wh:
            warehouse_id = scoped_wh
    else:
        q = q.filter(_non_admin_visibility_filter(current_user))

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

    # Project down to only the columns the list view needs (AssetListOut), 
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
    # UUID-typed for the same reason as list_assets above, a malformed
    # value now 422s cleanly instead of crashing with an uncaught 500.
    warehouse_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    assigned_to: UUID | None = Query(default=None),
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
    is_assigned: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(Asset)

    # Warehouse scoping (see list_assets).
    if is_admin_role(current_user):
        scoped_wh = _enforced_warehouse(current_user)
        if scoped_wh:
            warehouse_id = scoped_wh
    else:
        q = q.filter(_non_admin_visibility_filter(current_user))

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
    # These filters (health_band, make/model/year, numeric ranges) must stay
    # in step with list_assets. FastAPI ignores unknown query params instead
    # of erroring, so any filter missing here returns an unfiltered fleet-wide
    # count next to correctly-filtered rows, which breaks the toolbar's
    # "N assets" badge and pagination.
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
    if is_admin_role(current_user):
        scoped_wh = _enforced_warehouse(current_user)
        if scoped_wh:
            q = q.filter(Asset.warehouse_id == scoped_wh)
    else:
        scoped_wh = None
        q = q.filter(_non_admin_visibility_filter(current_user))

    # Real values of the asset_status Postgres enum: active, inactive,
    # under_maintenance, critical, decommissioned.
    row = q.with_entities(
        func.count(Asset.id),
        func.count(Asset.id).filter(cast(Asset.status, String) == "active"),
        func.count(Asset.id).filter(cast(Asset.status, String) == "under_maintenance"),
        func.count(Asset.id).filter(Asset.health_band == "critical"),
        func.count(Asset.id).filter(cast(Asset.status, String).in_(("inactive", "decommissioned"))),
    ).one()

    total, operational, maintenance, critical, offline = row
    total = int(total or 0)

    # Real per-asset health_score average from pdm_batch_predictions, the
    # same source and same number the admin dashboard's Fleet Health KPI
    # uses. Averaged ONLY over assets that actually have a completed
    # prediction; NOT blended with any estimate for unscored assets, so
    # this number is always the true average of real model output, never
    # part-real-part-guessed. scoredCount tells the frontend how many of
    # the total assets that average actually covers, so it can show "N of
    # M assets" honestly instead of implying full fleet coverage.
    health_q = (
        db.query(func.avg(PdmBatchPrediction.health_score), func.count(PdmBatchPrediction.asset_id))
        .select_from(Asset)
        .join(
            PdmBatchPrediction,
            (PdmBatchPrediction.asset_id == Asset.id) & (PdmBatchPrediction.status == "ok"),
        )
    )
    if is_admin_role(current_user):
        if scoped_wh:
            health_q = health_q.filter(Asset.warehouse_id == scoped_wh)
    else:
        health_q = health_q.filter(_non_admin_visibility_filter(current_user))
    avg_health_score, scored_count = health_q.one()
    scored_count = int(scored_count or 0)

    return {
        "total": total,
        "operational": int(operational or 0),
        "maintenance": int(maintenance or 0),
        "critical": int(critical or 0),
        "offline": int(offline or 0),
        "avgHealth": round(float(avg_health_score), 0) if avg_health_score is not None else None,
        "avgHealthScoredCount": scored_count,
    }


@router.get("/analytics")
def get_asset_analytics(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Fleet-wide descriptive analytics for the AssetsAnalytics charts:
    status distribution, health-band distribution, vehicle-type breakdown,
    and the top 5 at-risk assets. Computed over ALL matching assets (scoped
    to the caller's warehouse), independent of pagination, so the charts
    don't silently reflect only whatever page of the table is showing.
    """
    base_q = db.query(Asset)
    if is_admin_role(current_user):
        scoped_wh = _enforced_warehouse(current_user)
        if scoped_wh:
            base_q = base_q.filter(Asset.warehouse_id == scoped_wh)
    else:
        base_q = base_q.filter(_non_admin_visibility_filter(current_user))

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

    # Top 5 at-risk: critical first, then poor, each ordered by criticality_score
    # ascending (worst first), despite the name, criticality_score is used
    # fleet-wide (profile.py, user_profile.py, users.py) as a health-percentage
    # proxy where higher = healthier (defaults to 100.0 when null), so the most
    # at-risk assets within a band are the ones with the LOWEST score, not the
    # highest.
    risk_order = case(
        (Asset.health_band == "critical", 0),
        (Asset.health_band == "poor", 1),
        else_=2,
    )
    at_risk_rows = (
        base_q.filter(Asset.health_band.in_(("critical", "poor")))
        .with_entities(Asset.id, Asset.asset_name, Asset.asset_code, Asset.health_band)
        .order_by(risk_order, Asset.criticality_score.asc().nullslast())
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
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    if is_admin_role(current_user):
        _assert_asset_in_scope(obj, current_user)
    elif not user_can_view_asset(obj, current_user):
        # 404, not 403, same rationale as _assert_asset_in_scope: don't
        # reveal that an asset outside the caller's warehouse exists.
        raise HTTPException(status_code=404, detail="Asset not found")
    return obj


@router.put("/{asset_id}", response_model=AssetOut, dependencies=[Depends(require_admin)])
def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    update_data = payload.model_dump(exclude_unset=True)

    # A regular admin is pinned to one warehouse and must never be able to
    # move an asset into a different one via this endpoint, create_asset
    # already prevents this on the create path by pinning warehouse_id
    # server-side, but update_asset had no equivalent, so a regular admin
    # could relocate an asset out of their own warehouse boundary just by
    # including warehouse_id in the PUT body. super_admins may still
    # deliberately move an asset between warehouses.
    if "warehouse_id" in update_data and not is_super_admin(current_user):
        del update_data["warehouse_id"]

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

    # Same check as create_asset: a nonexistent department_id would otherwise
    # raise an uncaught IntegrityError on commit instead of a clean 404.
    if update_data.get("department_id"):
        existing_dept = db.query(Department).filter(Department.id == update_data["department_id"]).first()
        if not existing_dept:
            raise HTTPException(status_code=404, detail="Department not found")

    for key, value in update_data.items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/{asset_id}/assign", response_model=AssetOut, dependencies=[Depends(require_admin)])
def assign_asset(
    asset_id: UUID,
    assigned_to: UUID | None = None,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Assign an asset to a user, or unassign it by omitting `assigned_to`.

    Admin only. Two things are written together: `assets.assigned_to`, which
    drives visibility and every "my assets" view, and a row in
    `asset_assignments`, which is the audit trail of who assigned what to whom.
    Writing only the first would leave the history permanently empty.
    """
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    assignee: Profile | None = None
    if assigned_to is not None:
        assignee = db.query(Profile).filter(Profile.id == assigned_to).first()
        if not assignee:
            raise HTTPException(status_code=404, detail="User not found")

        # An asset can only be worked on by someone at its site, so refuse a
        # cross-warehouse assignment rather than creating one nobody can act on.
        if assignee.warehouse_id is not None and str(assignee.warehouse_id) != str(obj.warehouse_id):
            raise HTTPException(
                status_code=422,
                detail="That user belongs to a different warehouse than this asset.",
            )

        if (assignee.status or "").strip().lower() != "active":
            raise HTTPException(
                status_code=422,
                detail="That user account is not active.",
            )

    previous = obj.assigned_to
    now = datetime.utcnow()

    try:
        # Close whatever assignment was open, whether this is a reassignment
        # or an unassignment.
        (
            db.query(AssetAssignment)
            .filter(
                AssetAssignment.asset_id == asset_id,
                AssetAssignment.is_active == True,  # noqa: E712
            )
            .update(
                {"is_active": False, "unassigned_at": now},
                synchronize_session=False,
            )
        )

        obj.assigned_to = assigned_to

        if assigned_to is not None:
            db.add(
                AssetAssignment(
                    asset_id=asset_id,
                    user_id=assigned_to,
                    assigned_by=current_user.id,
                    is_active=True,
                    notes=notes,
                )
            )

        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to assign asset %s to %s", asset_id, assigned_to)
        raise HTTPException(status_code=500, detail="Could not update the assignment")

    db.refresh(obj)

    # Best-effort: the assignment is already committed, so a failed
    # notification must not fail the request.
    if assigned_to is not None and str(previous or "") != str(assigned_to):
        try:
            from app.services.in_app_notification_service import InAppNotificationService

            InAppNotificationService.notify_user(
                db,
                user_id=str(assigned_to),
                title="Asset assigned to you",
                message=f"{obj.asset_name or obj.asset_code} has been assigned to you.",
                priority="medium",
                notification_type="system",
                link_url=f"/user/assets?asset_id={asset_id}",
            )
        except Exception:
            log.exception("Asset-assignment notification failed (non-fatal)")

    return obj


@router.patch("/{asset_id}/status", response_model=AssetOut, dependencies=[Depends(require_admin)])
def update_asset_status(
    asset_id: UUID,
    status: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    # Validated against the enum before it is stored. An unchecked status
    # would "succeed" here and then drop out of every dashboard bucket, since
    # get_asset_stats counts only the real enum values.
    normalized = status.strip().lower()
    if normalized not in _VALID_ASSET_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Valid: {sorted(_VALID_ASSET_STATUSES)}",
        )

    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    obj.status = normalized
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{asset_id}", dependencies=[Depends(require_admin)])
def delete_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(Asset).filter(Asset.id == asset_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(obj, current_user)

    try:
        _purge_asset(db, asset_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Cannot delete asset: {getattr(exc, 'orig', exc)}")
    return {"message": "Asset deleted successfully"}


@router.post(
    "/{asset_id}/send-service-reminder",
    summary="Send a service reminder email to the assigned user (admin only)",
)
def send_service_reminder_endpoint(
    asset_id: UUID,
    payload: ServiceReminderRequest | None = None,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Admin-triggered manual send with optional note included in the email."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admins only")

    # asset_id is UUID-typed above, so FastAPI rejects a malformed value with
    # a clean 422 before this body runs and no manual parsing is needed.

    # The asset is looked up so the warehouse check below can run. Without it
    # any admin, whichever warehouse they are pinned to, could trigger a
    # service-reminder email for an asset they do not manage.
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _assert_asset_in_scope(asset, current_user)

    note = payload.note.strip() if payload and payload.note else None

    try:
        result = send_manual_reminder(
            db,
            asset_id=asset_id,
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