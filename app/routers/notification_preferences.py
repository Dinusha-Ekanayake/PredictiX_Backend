"""Per-user notification preferences.

Every endpoint here is scoped to the caller. Previously none of them took the
caller's identity into account at all: the create took a ``user_id`` from the
request body, the list took one from the query string, and the delete accepted
any preference id — so any authenticated user could set, read or remove another
person's notification settings. Administrators may still act on anyone, which
is what makes support able to fix a colleague's settings.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, is_admin_role, require_user
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
def create_user_notification_preference(
    payload: UserNotificationPreferenceCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    if not is_admin_role(current_user) and str(payload.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="You can only set your own notification preferences"
        )

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
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(UserNotificationPreference)
    if is_admin_role(current_user):
        # Admins may inspect a specific person, or everyone when unfiltered.
        if user_id:
            q = q.filter(UserNotificationPreference.user_id == user_id)
    else:
        # A non-admin always reads their own, whatever the query string says.
        q = q.filter(UserNotificationPreference.user_id == current_user.id)
    return q.offset(offset).limit(limit).all()


@router.delete("/{preference_id}")
def delete_user_notification_preference(
    preference_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(UserNotificationPreference).filter(
        UserNotificationPreference.id == preference_id
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Notification preference not found")
    if not is_admin_role(current_user) and str(obj.user_id) != str(current_user.id):
        # 404 rather than 403: whether someone else's preference exists is not
        # something a caller who cannot touch it needs to learn.
        raise HTTPException(status_code=404, detail="Notification preference not found")
    db.delete(obj)
    db.commit()
    return {"message": "Notification preference deleted"}