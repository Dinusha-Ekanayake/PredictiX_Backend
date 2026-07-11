from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, is_admin_role, require_admin, require_user
from app.models import AssetAssignment
from app.schemas.misc import AssetAssignmentCreate, AssetAssignmentOut

router = APIRouter(
    prefix="/asset-assignments",
    tags=["Asset Assignments"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=AssetAssignmentOut, dependencies=[Depends(require_admin)])
def create_asset_assignment(payload: AssetAssignmentCreate, db: Session = Depends(get_db)):
    obj = AssetAssignment(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetAssignmentOut])
def list_asset_assignments(
    asset_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(AssetAssignment)

    # Regular users only ever see assignment history involving themselves —
    # otherwise the shared asset-details panel's Assignments tab (called
    # with ?asset_id=) would expose every other employee's assignment
    # history, admin notes, and reassignment dates for any asset.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.filter(cast(AssetAssignment.user_id, String) == uid)

    if asset_id:
        q = q.filter(AssetAssignment.asset_id == asset_id)
    if user_id:
        q = q.filter(AssetAssignment.user_id == user_id)
    return q.order_by(AssetAssignment.assigned_at.desc()).offset(offset).limit(limit).all()


@router.delete("/{assignment_id}", dependencies=[Depends(require_admin)])
def delete_asset_assignment(assignment_id: str, db: Session = Depends(get_db)):
    obj = db.query(AssetAssignment).filter(AssetAssignment.id == assignment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset assignment not found")
    db.delete(obj)
    db.commit()
    return {"message": "Asset assignment deleted"}