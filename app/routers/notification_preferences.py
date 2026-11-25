"""Per-user notification preferences.

Every endpoint here is scoped to the caller, and none of them take the subject
from the request. A ``user_id`` in the body, one in the query string, or a bare
preference id would each let any authenticated user set, read or remove another
person's notification settings. Administrators may act on anyone, which is what
makes support able to fix a colleague's settings.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import (
    get_db, get_current_user, is_admin_role, require_user,
    assert_can_manage_user, is_super_admin, scoped_warehouse_id,
)
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
    if str(user.id) != str(current_user.id):
        assert_can_manage_user(current_user, user)

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
        # Admins may inspect a specific person they manage, or everyone they
        # manage when unfiltered. A super admin manages every account.
        if user_id:
            target = db.query(Profile).filter(Profile.id == user_id).first()
            if target is None:
                return []
            if str(target.id) != str(current_user.id):
                assert_can_manage_user(current_user, target)
            q = q.filter(UserNotificationPreference.user_id == user_id)
        elif not is_super_admin(current_user):
            q = q.join(Profile, Profile.id == UserNotificationPreference.user_id).filter(
                Profile.warehouse_id == scoped_warehouse_id(current_user),
                Profile.role != "super_admin",
            )
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
    if str(obj.user_id) != str(current_user.id):
        # 404 rather than 403: whether someone else's preference exists is not
        # something a caller who cannot touch it needs to learn.
        if not is_admin_role(current_user):
            raise HTTPException(status_code=404, detail="Notification preference not found")
        owner = db.query(Profile).filter(Profile.id == obj.user_id).first()
        try:
            if owner is not None:
                assert_can_manage_user(current_user, owner)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Notification preference not found")
    db.delete(obj)
    db.commit()
    return {"message": "Notification preference deleted"}