from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import Profile
from app.schemas.profile import ProfileUpdate, ProfileOut

router = APIRouter(prefix="/profiles", tags=["Profiles"])


@router.get("/", response_model=list[ProfileOut])
def list_profiles(
    role: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Profile)
    if role:
        q = q.filter(Profile.role == role)
    if department_id:
        q = q.filter(Profile.department_id == department_id)
    if warehouse_id:
        q = q.filter(Profile.warehouse_id == warehouse_id)
    return q.order_by(Profile.full_name).all()


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")
    return obj


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj