from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import AssetAssignment
from app.schemas.misc import AssetAssignmentCreate, AssetAssignmentOut

router = APIRouter(prefix="/asset-assignments", tags=["Asset Assignments"])


@router.post("/", response_model=AssetAssignmentOut)
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
    db: Session = Depends(get_db),
):
    q = db.query(AssetAssignment)
    if asset_id:
        q = q.filter(AssetAssignment.asset_id == asset_id)
    if user_id:
        q = q.filter(AssetAssignment.user_id == user_id)
    return q.order_by(AssetAssignment.assigned_at.desc()).all()


@router.delete("/{assignment_id}")
def delete_asset_assignment(assignment_id: str, db: Session = Depends(get_db)):
    obj = db.query(AssetAssignment).filter(AssetAssignment.id == assignment_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset assignment not found")
    db.delete(obj)
    db.commit()
    return {"message": "Asset assignment deleted"}