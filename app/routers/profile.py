"""Profiles router.

    GET    /profiles                 list profiles (admin)
    GET    /profiles/{id}            fetch profile (admin)
    PUT    /profiles/{id}            update profile (admin, schema-based)

    GET    /profiles/me              the authenticated user's full profile
    PUT    /profiles/me              update self (name/phone/address)
    GET    /profiles/me/assets       assets assigned to self
    GET    /profiles/me/stats        asset counts for self
    GET    /profiles/me/colleagues   other users in self's department
"""
from __future__ import annotations

import logging

import io
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_admin, require_user, active_warehouse_id
from app.models import Asset, AssetAssignment, Department, PdmBatchPrediction, Profile, Warehouse
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.schemas.user_profile import UserProfileUpdate
from app.services.notification_service import NotificationService

log = logging.getLogger(__name__)
# Every endpoint needs a valid token. The admin-only list/{id} endpoints add
# require_admin individually; the /me* endpoints resolve the caller themselves.
router = APIRouter(
    prefix="/profiles",
    tags=["Profiles"],
    dependencies=[Depends(require_user)],
)


# ─── Admin endpoints ──────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProfileOut], dependencies=[Depends(require_admin)])
def list_profiles(
    role: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(Profile)
    if role:
        q = q.filter(Profile.role == role)
    if department_id:
        q = q.filter(Profile.department_id == department_id)

    # Scope to the caller's active warehouse; overrides any client-supplied
    # warehouse_id so an admin can't enumerate another warehouse's profiles.
    scoped_wh = active_warehouse_id(current_user)
    if scoped_wh:
        warehouse_id = scoped_wh
    if warehouse_id:
        q = q.filter(Profile.warehouse_id == warehouse_id)
    return q.order_by(Profile.full_name).offset(offset).limit(limit).all()


# ─── Self-service endpoints (/profiles/me) ────────────────────────────────────
# NOTE: these literal "/me" routes are defined BEFORE the parametrized
# "/{profile_id}" routes (at the bottom of this file) so that a request to
# /profiles/me is not captured by /{profile_id} with profile_id="me".

def _split_name(full: str | None) -> tuple[str, str]:
    parts = (full or "").split(" ")
    return parts[0] if parts else "", " ".join(parts[1:]) if len(parts) > 1 else ""


def _profile_to_response(user: Profile, db: Session) -> dict:
    """Build the frontend-friendly self-profile shape.

    Department name, warehouse name and assigned-asset count come back in one
    statement of three scalar subqueries. Each round trip to Supabase costs
    roughly 250ms regardless of how little it returns, so the count of
    statements matters more here than the work inside them.

    The asset count is the union of the direct assigned_to column and active
    asset_assignments rows, excluding only decommissioned assets. Filtering on
    status == "active" would undercount a user's assets the moment one goes
    critical or under_maintenance, which is when they most need to see it.
    """
    row = db.execute(
        text("""
            SELECT
              (SELECT name FROM departments WHERE id = :dept_id)  AS department_name,
              (SELECT name FROM warehouses  WHERE id = :wh_id)    AS warehouse_name,
              (SELECT count(*) FROM assets a
                 WHERE (a.assigned_to = :uid
                        OR a.id IN (SELECT asset_id FROM asset_assignments
                                     WHERE user_id = :uid AND is_active))
                   AND a.status::text <> 'decommissioned')        AS asset_count
        """),
        {
            "dept_id": user.department_id,
            "wh_id": user.warehouse_id,
            "uid": user.id,
        },
    ).first()

    department_name = row[0] if row else None
    warehouse_name = row[1] if row else None
    asset_count = int(row[2]) if row and row[2] is not None else 0

    first_name, last_name = _split_name(user.full_name)
    meta = user.meta if isinstance(user.meta, dict) else {}
    address = meta.get("address")
    # Preference toggles live in meta['settings']; default sensibly when unset
    # so the Settings page renders consistent values for first-time users.
    saved_settings = meta.get("settings") or {}
    settings = {
        "emailNotifications": saved_settings.get("emailNotifications", True),
        "criticalAlerts": saved_settings.get("criticalAlerts", True),
        "maintenanceAlerts": saved_settings.get("maintenanceAlerts", True),
        "compactView": saved_settings.get("compactView", False),
    }

    return {
        "id": str(user.id),
        "employee_id": user.employee_id,
        "firstName": first_name,
        "lastName": last_name,
        "name": user.full_name or "",
        "email": user.email or "",
        "contactNumber": user.phone,
        "address": address,
        "department": department_name,
        "department_id": str(user.department_id) if user.department_id else None,
        "warehouse": warehouse_name,
        "warehouse_id": str(user.warehouse_id) if user.warehouse_id else None,
        "role": user.role or "",
        "status": user.status or "",
        "assignedAssetsCount": asset_count,
        "avatar_url": user.avatar_url or None,
        "settings": settings,
    }


@router.get("/me")
def get_my_profile(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # get_current_user has already loaded this row by primary key, so it is
    # passed straight through rather than fetched again.
    return _profile_to_response(current_user, db)


from fastapi import BackgroundTasks

@router.put("/me")
def update_my_profile(
    payload: UserProfileUpdate,
    background_tasks: BackgroundTasks,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # PATCH semantics: "the client did not mention this field" and "the client
    # explicitly sent null to clear it" are different requests, and testing
    # `is not None` collapsed them into one, so a user could set an address or
    # phone number but never clear it again, and the API silently returned 200
    # as though the clear had worked. model_fields_set carries only the keys
    # actually present in the request body, which is the distinction we need.
    sent = payload.model_fields_set

    if "firstName" in sent or "lastName" in sent:
        curr_first, curr_last = _split_name(current_user.full_name)
        first = payload.firstName if "firstName" in sent else curr_first
        last = payload.lastName if "lastName" in sent else curr_last
        # A name is identity, not free text: refuse to blank it entirely rather
        # than storing an empty string that renders as a nameless account.
        combined = f"{first or ''} {last or ''}".strip()
        if not combined:
            raise HTTPException(
                status_code=422,
                detail="firstName and lastName cannot both be empty",
            )
        current_user.full_name = combined

    if "contactNumber" in sent:
        current_user.phone = payload.contactNumber or None

    if "address" in sent:
        meta = dict(current_user.meta or {})
        if payload.address:
            meta["address"] = payload.address
        else:
            # Drop the key entirely rather than storing null/"", keeps meta
            # clean and makes "no address" a single representation.
            meta.pop("address", None)
        current_user.meta = meta

    if payload.settings is not None:
        meta = dict(current_user.meta or {})
        existing = dict(meta.get("settings") or {})
        # Merge only the keys the client actually sent (exclude unset/None) so a
        # partial settings update doesn't wipe other toggles.
        incoming = payload.settings.model_dump(exclude_none=True)
        existing.update(incoming)
        meta["settings"] = existing
        current_user.meta = meta

    if db and hasattr(current_user, "__table__"):
        try:
            db.commit()
            db.refresh(current_user)
        except Exception:
            db.rollback()
            log.exception("Profile update failed")
            raise HTTPException(status_code=500, detail="Profile update failed")

        def send_notifications():
            # Best-effort admin notification email via Brevo, never blocks the save.
            try:
                NotificationService.notify_on_profile_update(db, str(current_user.id))
            except Exception:
                log.exception("Profile-update notification failed (non-fatal)")

            # In-app bell notification for admins
            try:
                from app.services.in_app_notification_service import InAppNotificationService
                InAppNotificationService.notify_admins(
                    db=db,
                    title="Profile Updated",
                    message=f"{current_user.full_name} has updated their profile information.",
                    priority="low",
                    notification_type="system",
                    warehouse_id=str(current_user.warehouse_id) if current_user.warehouse_id else None
                )
            except Exception:
                log.exception("Profile-update in-app notification failed (non-fatal)")

        background_tasks.add_task(send_notifications)

    return _profile_to_response(current_user, db)


@router.post("/me/avatar")
def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB.")

    ext = (file.filename or "avatar.jpg").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "gif", "webp"}:
        ext = "jpg"

    user_id = str(current_user.id)
    filename = f"{user_id}/{_uuid.uuid4()}.{ext}"

    try:
        from app.db.supabase_client import supabase
        supabase.storage.from_("avatars").upload(
            path=filename,
            file=contents,
            file_options={"content-type": file.content_type, "upsert": "true"},
        )
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        avatar_url = f"{supabase_url}/storage/v1/object/public/avatars/{filename}"
    except Exception as e:
        log.warning("[AVATAR] Supabase upload failed: %s — falling back to base64", e)
        import base64
        b64 = base64.b64encode(contents).decode()
        avatar_url = f"data:{file.content_type};base64,{b64}"

    real_user = db.query(Profile).filter(Profile.id == current_user.id).first()
    if not real_user:
        raise HTTPException(status_code=404, detail="Profile not found.")

    real_user.avatar_url = avatar_url
    try:
        db.commit()
        db.refresh(real_user)
    except Exception:
        db.rollback()
        log.exception("Failed to save avatar_url")
        raise HTTPException(status_code=500, detail="Failed to save avatar.")

    return {"avatar_url": avatar_url}


@router.get("/me/assets")
def get_my_assets(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db:
        return []

    # Assigned via either the direct assets.assigned_to column OR an active
    # row in asset_assignments, an asset reassigned only through the
    # assignments table (without updating assigned_to) would otherwise
    # silently be missing from this list despite showing up elsewhere
    # (get_my_profile's asset count already checks both sources via
    # max(direct, via_table)). Only decommissioned (fully retired) assets
    # are excluded, critical/under_maintenance assets must still show up,
    # since those are exactly what most need the user's attention.
    assigned_asset_ids_subq = (
        db.query(AssetAssignment.asset_id)
        .filter(AssetAssignment.user_id == current_user.id, AssetAssignment.is_active == True)
    )
    assets = (
        db.query(Asset)
        .filter(
            or_(
                Asset.assigned_to == str(current_user.id),
                Asset.id.in_(assigned_asset_ids_subq),
            ),
            cast(Asset.status, String) != "decommissioned",
        )
        .all()
    )

    warehouse_ids = {a.warehouse_id for a in assets if a.warehouse_id is not None}
    warehouses_by_id = {
        w.id: w
        for w in db.query(Warehouse.id, Warehouse.name, Warehouse.city).filter(Warehouse.id.in_(warehouse_ids)).all()
    } if warehouse_ids else {}

    # healthPercent comes from pdm_batch_predictions.health_score, resolved for
    # every asset in one query.
    #
    # criticality_score is not a substitute. It measures how important an asset
    # is, not how healthy, and the two barely track each other: across the fleet
    # they differ by 29 points on average. The UI draws this value straight into
    # a coloured health bar, so the wrong source shows a reassuring number for
    # failing equipment.
    asset_ids = [a.id for a in assets]
    health_by_asset: dict = {}
    if asset_ids:
        health_by_asset = {
            row.asset_id: row.health_score
            for row in db.query(
                PdmBatchPrediction.asset_id, PdmBatchPrediction.health_score
            ).filter(
                PdmBatchPrediction.asset_id.in_(asset_ids),
                PdmBatchPrediction.status == "ok",
            ).all()
        }

    result = []
    for asset in assets:
        location = ""
        wh = warehouses_by_id.get(asset.warehouse_id)
        if wh:
            location = wh.name
            if wh.city:
                location += f" - {wh.city}"

        result.append({
            "assignment_id": str(asset.id),
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "name": asset.asset_name,
            "asset_type": asset.asset_type,
            "category": asset.category,
            "location": location,
            "status": asset.status or "active",
            # None, not 100.0, when the asset has no completed prediction: the
            # UI already renders null as ", ", whereas the old default asserted
            # perfect health for an asset nothing had actually scored.
            "healthPercent": (
                float(health_by_asset[asset.id])
                if health_by_asset.get(asset.id) is not None else None
            ),
            "nextServiceDate": asset.next_service_date.isoformat() if asset.next_service_date else None,
        })
    return result


@router.get("/me/stats")
def get_my_stats(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db:
        return {"assignedAssets": 0, "activeAssets": 0}

    # assignedAssets = everything assigned to this user (direct assigned_to
    # OR an active asset_assignments row, same union as get_my_assets)
    # except fully decommissioned assets; activeAssets = specifically
    # status == "active". The two counts differ on purpose: a critical or
    # under_maintenance asset is still assigned to its holder even though it is
    # not active.
    assigned_asset_ids_subq = (
        db.query(AssetAssignment.asset_id)
        .filter(AssetAssignment.user_id == current_user.id, AssetAssignment.is_active == True)
    )
    # Both counts come from the same rows and differ only by status, so they are
    # two aggregates over one scan rather than two queries. The database is in a
    # different region from the application (~150-230ms per round-trip), which
    # makes an avoidable second query the dominant cost of this endpoint.
    row = (
        db.query(
            func.count(Asset.id)
            .filter(cast(Asset.status, String) != "decommissioned")
            .label("assigned"),
            func.count(Asset.id)
            .filter(cast(Asset.status, String) == "active")
            .label("active"),
        )
        .filter(
            or_(
                Asset.assigned_to == str(current_user.id),
                Asset.id.in_(assigned_asset_ids_subq),
            )
        )
        .one()
    )
    return {"assignedAssets": int(row.assigned or 0), "activeAssets": int(row.active or 0)}


@router.get("/me/colleagues")
def get_my_colleagues(
    limit: int | None = Query(default=None, ge=1, le=1000,
                              description="Cap the number of colleagues returned. "
                                          "Omit for the full department (the team "
                                          "directory needs all of them to search over)."),
    offset: int = Query(default=0, ge=0),
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Colleagues in the caller's department.

    Departments are per-warehouse rows, so filtering on ``department_id``
    already scopes this to the caller's own site.

    ``limit`` exists because the dashboard's "My Team" card renders eight
    people: unbounded, this returned the entire department, measured at 519
    colleagues / 140 KB for one Colombo driver, ~98% of it discarded, and the
    slowest of that page's four parallel calls. The team directory still omits
    the parameter and receives everyone, because it filters client-side.
    """
    # current_user is the caller's own Profile row and already carries
    # department_id, so no lookup is needed here.
    if not current_user.department_id:
        return []

    q = (
        db.query(Profile)
        .filter(Profile.department_id == current_user.department_id,
                Profile.id != current_user.id)
        .order_by(Profile.full_name)
    )
    if offset:
        q = q.offset(offset)
    if limit is not None:
        q = q.limit(limit)
    colleagues = q.all()

    # All colleagues share the same department, resolve the name once
    # instead of one Department query per colleague (removes the N+1).
    dept = db.query(Department).filter(Department.id == current_user.department_id).first()
    dept_name = dept.name if dept else "Unknown"

    result = []
    for member in colleagues:
        first_name, last_name = _split_name(member.full_name)
        result.append({
            "id": str(member.id),
            "employee_id": member.employee_id,
            "firstName": first_name,
            "lastName": last_name,
            "name": member.full_name,
            "email": member.email,
            "contactNumber": member.phone,
            "department": dept_name,
            "role": member.role,
            "status": member.status,
        })
    return result


# ─── Admin endpoints with a path param (registered LAST) ──────────────────────
# Must come after the literal "/me*" routes above, otherwise "/{profile_id}"
# greedily matches "me" and shadows the self-service profile endpoint.

@router.get("/{profile_id}", response_model=ProfileOut, dependencies=[Depends(require_admin)])
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")
    return obj


@router.put("/{profile_id}", response_model=ProfileOut, dependencies=[Depends(require_admin)])
def update_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(get_db)):
    obj = db.query(Profile).filter(Profile.id == profile_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Profile not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj
