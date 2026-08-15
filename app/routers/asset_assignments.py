from uuid import UUID

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
    active_warehouse_id,
)
from app.models import Asset, AssetAssignment, Profile
from app.schemas.misc import AssetAssignmentCreate, AssetAssignmentOut

router = APIRouter(
    prefix="/asset-assignments",
    tags=["Asset Assignments"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=AssetAssignmentOut, dependencies=[Depends(require_admin)])
def create_asset_assignment(
    payload: AssetAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    # Previously trusted the raw payload entirely: asset_id/user_id were
    # never validated to exist, the target asset's warehouse was never
    # checked against the caller's, and assigned_by was taken verbatim from
    # the client instead of the authenticated session — any admin could
    # assign a different warehouse's asset to an arbitrary user_id and
    # attribute the action to someone else.
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

    user = db.query(Profile).filter(Profile.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump()
    data["assigned_by"] = current_user.id
    obj = AssetAssignment(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetAssignmentOut])
def list_asset_assignments(
    asset_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(AssetAssignment)

    # Regular users only ever see assignment history involving themselves —
    # otherwise the shared asset-details panel's Assignments tab (called
    # with ?asset_id=) would expose every other employee's assignment
    # history, admin notes, and reassignment dates for any asset. Admins
    # are scoped to their active warehouse — previously unscoped, so any
    # admin saw every warehouse's assignment history.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.filter(cast(AssetAssignment.user_id, String) == uid)
    else:
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            q = q.join(Asset, Asset.id == AssetAssignment.asset_id).filter(Asset.warehouse_id == wh_id)

    if asset_id:
        q = q.filter(AssetAssignment.asset_id == asset_id)
    if user_id:
        q = q.filter(AssetAssignment.user_id == user_id)

    rows = q.order_by(AssetAssignment.assigned_at.desc()).offset(offset).limit(limit).all()

    # Resolve the people involved in one query rather than one per row, so the
    # history can show names instead of UUIDs.
    person_ids = {r.user_id for r in rows if r.user_id}
    person_ids |= {r.assigned_by for r in rows if r.assigned_by}
    people = {
        p.id: p
        for p in db.query(Profile.id, Profile.full_name, Profile.email)
        .filter(Profile.id.in_(person_ids))
        .all()
    } if person_ids else {}

    out: list[AssetAssignmentOut] = []
    for r in rows:
        assignee = people.get(r.user_id)
        assigner = people.get(r.assigned_by)
        item = AssetAssignmentOut.model_validate(r)
        item.user_name = assignee.full_name if assignee else None
        item.user_email = assignee.email if assignee else None
        item.assigned_by_name = assigner.full_name if assigner else None
        out.append(item)
    return out


@router.delete("/{assignment_id}", dependencies=[Depends(require_admin)])
def delete_asset_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(AssetAssignment).filter(AssetAssignment.id == assignment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset assignment not found")
    # Previously unscoped — any admin could delete any warehouse's
    # assignment history record by ID.
    asset = db.query(Asset).filter(Asset.id == obj.asset_id).first()
    if asset is not None:
        assert_asset_in_scope(asset, current_user)
    db.delete(obj)
    db.commit()
    return {"message": "Asset assignment deleted"}