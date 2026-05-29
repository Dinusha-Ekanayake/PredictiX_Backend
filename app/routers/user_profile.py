from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user
from app.models import Profile, Warehouse, Department, Asset, AssetAssignment, AssetFailurePrediction
from app.schemas.user_profile import (
    UserProfileOut,
    UserProfileUpdate,
    UserAssignedAssetOut,
    UserItemOut,
    UserCreate,
    UserUpdate
)
from app.services.notification_service import NotificationService
from typing import List
import uuid
import traceback

router = APIRouter(prefix="/user-profile", tags=["User Profile"])

@router.get("/me")
def get_my_profile(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # Get real user from database
        email = current_user.email
        real_user = db.query(Profile).filter(Profile.email == email).first()
        
        if not real_user:
            # Fallback to current_user
            real_user = current_user
        
        # Get department name
        department_name = None
        if real_user.department_id:
            dept = db.query(Department).filter(Department.id == real_user.department_id).first()
            if dept:
                department_name = dept.name
        
        # Get warehouse name  
        warehouse_name = None
        if real_user.warehouse_id:
            wh = db.query(Warehouse).filter(Warehouse.id == real_user.warehouse_id).first()
            if wh:
                warehouse_name = wh.name
        
        # Asset count — check both direct assignment and assignment table
        asset_count = 0
        try:
            direct = db.query(Asset).filter(
                Asset.assigned_to == real_user.id,
                Asset.status != "retired"
            ).count()
            via_table = db.query(AssetAssignment).filter(
                AssetAssignment.user_id == real_user.id,
                AssetAssignment.is_active == True
            ).count()
            asset_count = max(direct, via_table)
        except:
            asset_count = 0
        
        # Parse name
        name_parts = (real_user.full_name or "").split(" ")
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        # Address
        address = None
        if real_user.meta and isinstance(real_user.meta, dict):
            address = real_user.meta.get("address")
        
        return {
            "id": str(real_user.id),
            "employee_id": real_user.employee_id,
            "firstName": first_name,
            "lastName": last_name,
            "name": real_user.full_name or "",
            "email": real_user.email or "",
            "contactNumber": real_user.phone,
            "address": address,
            "department": department_name,
            "department_id": str(real_user.department_id) if real_user.department_id else None,
            "warehouse": warehouse_name,
            "warehouse_id": str(real_user.warehouse_id) if real_user.warehouse_id else None,
            "role": real_user.role or "",
            "status": real_user.status or "",
            "assignedAssetsCount": asset_count
        }
        
    except Exception as e:
        print(f"[PROFILE ERROR] {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        return {
            "error": str(e)
        }

@router.put("/me", response_model=UserProfileOut)
def update_my_profile(
    payload: UserProfileUpdate,
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        if payload.firstName is not None or payload.lastName is not None:
            name_parts = (current_user.full_name or "").split(" ")
            curr_first = name_parts[0] if len(name_parts) > 0 else ""
            curr_last = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            new_first = payload.firstName if payload.firstName is not None else curr_first
            new_last = payload.lastName if payload.lastName is not None else curr_last
            current_user.full_name = f"{new_first} {new_last}".strip()

        if payload.contactNumber is not None:
            current_user.phone = payload.contactNumber

        if payload.address is not None:
            meta = current_user.meta or {}
            meta_copy = dict(meta)
            meta_copy["address"] = payload.address
            current_user.meta = meta_copy

        if db and hasattr(current_user, '__table__'):
            db.commit()
            db.refresh(current_user)
            try:
                NotificationService.notify_on_profile_update(db, str(current_user.id))
            except Exception as notification_error:
                print(f"[NOTIFICATION-ERROR] {str(notification_error)}", flush=True)

        return get_my_profile(current_user=current_user, db=db)
    except Exception as e:
        if db:
            db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/me/assets")
def get_my_assets(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import text as sql_text
    try:
        if not db:
            return []

        # Get the real profile email and resolve UUID via raw SQL (bypasses ORM type issues)
        email = current_user.email
        uid_row = db.execute(sql_text(
            "SELECT id FROM profiles WHERE email = :email LIMIT 1"
        ), {"email": email}).fetchone()

        if not uid_row:
            print(f"[ASSETS] no profile found for email={email}", flush=True)
            return []

        uid = str(uid_row.id)
        print(f"[ASSETS] email={email} uid={uid}", flush=True)

        rows = db.execute(sql_text("""
            SELECT
                a.id, a.asset_code, a.asset_name, a.asset_type, a.vehicle_type,
                a.category, a.status, a.criticality_score, a.next_service_date,
                a.make, a.model,
                w.name AS wh_name, w.city AS wh_city,
                sr.tire_health_pct, sr.brake_health_pct,
                sr.battery_health_pct, sr.oil_life_pct, sr.hydraulic_health_pct
            FROM assets a
            LEFT JOIN warehouses w ON w.id = a.warehouse_id
            LEFT JOIN LATERAL (
                SELECT tire_health_pct, brake_health_pct, battery_health_pct,
                       oil_life_pct, hydraulic_health_pct
                FROM sensor_readings
                WHERE asset_id = a.id
                ORDER BY recorded_at DESC
                LIMIT 1
            ) sr ON true
            WHERE a.assigned_to = :uid
              AND a.status != 'retired'
        """), {"uid": uid}).fetchall()

        print(f"[ASSETS] raw SQL returned {len(rows)} rows", flush=True)

        result = []
        for r in rows:
            loc = r.wh_name or ""
            if r.wh_city:
                loc += f" - {r.wh_city}"
            health = float(r.criticality_score) if r.criticality_score else 100.0
            result.append({
                "assignment_id": str(r.id),
                "asset_id": str(r.id),
                "asset_code": r.asset_code or "",
                "name": r.asset_name or "",
                "asset_type": r.vehicle_type or r.asset_type or "",
                "category": r.category or "",
                "make": r.make or "",
                "model": r.model or "",
                "location": loc,
                "status": r.status or "active",
                "healthPercent": round(health, 1),
                "nextServiceDate": r.next_service_date.isoformat() if r.next_service_date else None,
                "sensorHealth": {
                    "tire": round(float(r.tire_health_pct), 1) if r.tire_health_pct else None,
                    "brake": round(float(r.brake_health_pct), 1) if r.brake_health_pct else None,
                    "battery": round(float(r.battery_health_pct), 1) if r.battery_health_pct else None,
                    "oil": round(float(r.oil_life_pct), 1) if r.oil_life_pct else None,
                    "hydraulic": round(float(r.hydraulic_health_pct), 1) if r.hydraulic_health_pct else None,
                },
            })

        return result
    except Exception as e:
        print(f"[ASSETS-ERROR] {str(e)}", flush=True)
        traceback.print_exc()
        return []

@router.get("/me/stats")
def get_my_stats(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import text as sql_text
    try:
        if not db:
            return {"assignedAssets": 0, "activeAssets": 0}

        uid_row = db.execute(sql_text(
            "SELECT id FROM profiles WHERE email = :email LIMIT 1"
        ), {"email": current_user.email}).fetchone()

        if not uid_row:
            return {"assignedAssets": 0, "activeAssets": 0}

        uid = str(uid_row.id)

        total = db.execute(sql_text(
            "SELECT count(*) FROM assets WHERE assigned_to = :uid AND status != 'retired'"
        ), {"uid": uid}).scalar() or 0

        active = db.execute(sql_text(
            "SELECT count(*) FROM assets WHERE assigned_to = :uid AND status IN ('active','operational','critical')"
        ), {"uid": uid}).scalar() or 0

        return {"assignedAssets": int(total), "activeAssets": int(active)}
    except Exception as e:
        print(f"[STATS-ERROR] {str(e)}", flush=True)
        traceback.print_exc()
        return {"assignedAssets": 0, "activeAssets": 0}

@router.get("/users")
def get_all_users(
    db: Session = Depends(get_db)
):
    try:
        users = db.query(Profile).all()
        result = []
        for user in users:
            department_name = None
            if user.department_id:
                department_name = db.query(Department.name).filter(Department.id == user.department_id).scalar()
                
            warehouse_name = None
            if user.warehouse_id:
                warehouse_name = db.query(Warehouse.name).filter(Warehouse.id == user.warehouse_id).scalar()
                
            direct_cnt = db.query(Asset).filter(
                Asset.assigned_to == user.id,
                Asset.status != "retired"
            ).count()
            table_cnt = db.query(AssetAssignment).filter(
                AssetAssignment.user_id == user.id,
                AssetAssignment.is_active == True
            ).count()
            assigned_assets_count = max(direct_cnt, table_cnt)
            
            meta = user.meta or {}
            address = meta.get("address", "") if isinstance(meta, dict) else ""
            name_parts = (user.full_name or "").split(" ")
            first_name = name_parts[0] if len(name_parts) > 0 else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            
            result.append(UserItemOut(
                id=str(user.id),
                firstName=first_name,
                lastName=last_name,
                name=user.full_name or "Unknown",
                email=user.email or "",
                address=address,
                contactNumber=user.phone or "",
                warehouse=warehouse_name or "Not assigned",
                role=user.role or "user",
                department=department_name or "Not assigned",
                status=user.status or "inactive",
                assignedAssets=assigned_assets_count
            ))
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users", response_model=UserItemOut)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db)
):
    try:
        # Gracefully handle lookups for relational mappings
        dept = db.query(Department).filter(Department.name == data.department).first()
        wh = db.query(Warehouse).filter(Warehouse.name == data.warehouse).first()
        
        new_profile_id = uuid.uuid4()
        
        new_profile = Profile(
            id=new_profile_id,
            employee_id=data.id, 
            full_name=data.name,
            email=data.email,
            phone=data.contactNumber,
            role=data.role,
            status=data.status,
            department_id=dept.id if dept else None,
            warehouse_id=wh.id if wh else None,
            meta={"address": data.address}
        )
        
        db.add(new_profile)
        db.commit()
        
        # ============================================================
        # SEND NOTIFICATIONS (All data from PostgreSQL database)
        # ============================================================
        
        print(f"[USER-CREATED] New user created: {data.name} ({data.email}) in {data.department} as {data.role}")
        
        try:
            # Trigger notification service which queries database for all data
            # This method sends all notifications (to user, admins, and dept members)
            NotificationService.notify_on_new_user(db, str(new_profile_id))
        except Exception as notification_error:
            # Log but don't fail the user creation if notifications fail
            print(f"[NOTIFICATION-ERROR] Failed to send notifications: {str(notification_error)}")
            import traceback
            traceback.print_exc()
        
        return UserItemOut(
            id=str(new_profile.id),
            firstName=data.firstName,
            lastName=data.lastName,
            name=data.name,
            email=data.email,
            address=data.address,
            contactNumber=data.contactNumber,
            warehouse=wh.name if wh else data.warehouse,
            role=data.role,
            department=dept.name if dept else data.department,
            status=data.status,
            assignedAssets=0
        )
    except Exception as e:
        db.rollback()
        print(f"[USER-CREATE-ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/departments", response_model=List[str])
def list_user_departments(db: Session = Depends(get_db)):
    """Simple list of active department names for dropdowns"""
    return [d.name for d in db.query(Department).all()]

@router.get("/warehouses", response_model=List[str])
def list_user_warehouses(db: Session = Depends(get_db)):
    """Simple list of active warehouse names for dropdowns"""
    return [w.name for w in db.query(Warehouse).all()]

@router.get("/users/{user_id}/assets", response_model=List[UserAssignedAssetOut])
def get_user_assets(user_id: str, db: Session = Depends(get_db)):
    try:
        import uuid as _uuid
        try:
            uid = _uuid.UUID(user_id)
        except ValueError:
            return []

        direct_assets = db.query(Asset).filter(
            Asset.assigned_to == uid,
            Asset.status != "retired"
        ).all()

        assignment_rows = db.query(AssetAssignment).filter(
            AssetAssignment.user_id == uid,
            AssetAssignment.is_active == True
        ).all()
        extra_ids = {r.asset_id for r in assignment_rows} - {a.id for a in direct_assets}
        extra_assets = db.query(Asset).filter(Asset.id.in_(extra_ids)).all() if extra_ids else []
        assets = direct_assets + extra_assets
        
        result = []
        for asset in assets:
            wh = db.query(Warehouse).filter(Warehouse.id == asset.warehouse_id).first()
            loc = wh.name if wh else "Unknown"
            
            result.append(UserAssignedAssetOut(
                assignment_id=str(asset.id),
                asset_id=str(asset.id),
                asset_code=asset.asset_code,
                name=asset.asset_name,
                asset_type=asset.asset_type,
                category=asset.category,
                location=loc,
                status=asset.status or "active",
                healthPercent=float(asset.criticality_score or 100),
                nextServiceDate=asset.next_service_date.isoformat() if asset.next_service_date else None
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}", response_model=UserItemOut)
def update_any_user(user_id: str, data: UserUpdate, db: Session = Depends(get_db)):
    try:
        user = db.query(Profile).filter(Profile.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        if data.name: user.full_name = data.name
        if data.email: user.email = data.email
        if data.contactNumber: user.phone = data.contactNumber
        if data.role: user.role = data.role
        if data.status: user.status = data.status
        
        if data.department:
            dept = db.query(Department).filter(Department.name == data.department).first()
            if dept: user.department_id = dept.id
            
        if data.warehouse:
            wh = db.query(Warehouse).filter(Warehouse.name == data.warehouse).first()
            if wh: user.warehouse_id = wh.id
            
        if data.address:
            meta = user.meta or {}
            meta["address"] = data.address
            user.meta = meta
            
        db.commit()
        db.refresh(user)
        
        # Return UserItemOut format
        wh_name = db.query(Warehouse.name).filter(Warehouse.id == user.warehouse_id).scalar()
        dp_name = db.query(Department.name).filter(Department.id == user.department_id).scalar()
        
        return UserItemOut(
            id=str(user.id),
            firstName=user.full_name.split(" ")[0] if user.full_name else "",
            lastName=" ".join(user.full_name.split(" ")[1:]) if user.full_name and " " in user.full_name else "",
            name=user.full_name,
            email=user.email,
            address=user.meta.get("address", "") if user.meta else "",
            contactNumber=user.phone or "",
            warehouse=wh_name or "Not assigned",
            role=user.role,
            department=dp_name or "Not assigned",
            status=user.status,
            assignedAssets=max(
                db.query(Asset).filter(Asset.assigned_to == user.id, Asset.status != "retired").count(),
                db.query(AssetAssignment).filter(AssetAssignment.user_id == user.id, AssetAssignment.is_active == True).count()
            )
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/me/colleagues")
def get_team_members(
    current_user: Profile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all team members - GUARANTEED TO WORK"""
    try:
        # Get the user by email directly (more reliable than current_user)
        email = current_user.email
        real_user = db.query(Profile).filter(Profile.email == email).first()
        
        if not real_user or not real_user.department_id:
            print(f"[TEAM-DEBUG] No user or no department for {email}")
            return []
        
        print(f"[TEAM-DEBUG] User {real_user.full_name} is in dept {real_user.department_id}")
        
        # Get all other users in same department
        team_members = db.query(Profile).filter(
            Profile.department_id == real_user.department_id,
            Profile.id != real_user.id
        ).all()
        
        print(f"[TEAM-DEBUG] Found {len(team_members)} team members")
        
        result = []
        for member in team_members:
            dept = db.query(Department).filter(Department.id == member.department_id).first()
            result.append({
                "id": str(member.id),
                "employee_id": member.employee_id,
                "firstName": member.full_name.split()[0] if member.full_name else "",
                "lastName": " ".join(member.full_name.split()[1:]) if member.full_name and " " in member.full_name else "",
                "name": member.full_name,
                "email": member.email,
                "contactNumber": member.phone,
                "department": dept.name if dept else "Unknown",
                "role": member.role,
                "status": member.status
            })
        
        return result
        
    except Exception as e:
        print(f"[TEAM-ERROR] {str(e)}")
        traceback.print_exc()
        return []
