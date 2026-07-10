from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user
from app.models import Profile, UserNotificationPreference
from app.schemas.misc import (
    UserNotificationPreferenceCreate,
    UserNotificationPreferenceOut,
)

router = APIRouter(
    prefix="/notification-preferences",
    tags=["Notification Preferences"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=UserNotificationPreferenceOut)
def create_user_notification_preference(payload: UserNotificationPreferenceCreate, db: Session = Depends(get_db)):
    user = db.query(Profile).filter(Profile.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    obj = UserNotificationPreference(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[UserNotificationPreferenceOut])
def list_user_notification_preferences(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(UserNotificationPreference)
    if user_id:
        q = q.filter(UserNotificationPreference.user_id == user_id)
    return q.offset(offset).limit(limit).all()


@router.delete("/{preference_id}")
def delete_user_notification_preference(preference_id: str, db: Session = Depends(get_db)):
    obj = db.query(UserNotificationPreference).filter(UserNotificationPreference.id == preference_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Notification preference not found")
    db.delete(obj)
    db.commit()
    return {"message": "Notification preference deleted"}