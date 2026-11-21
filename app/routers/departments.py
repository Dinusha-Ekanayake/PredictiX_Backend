from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import (
    scoped_warehouse_id,
    assert_in_active_warehouse,
    get_db,
    get_current_user,
    require_admin,
    require_user,
    active_warehouse_id,
    _role_of,
    ADMIN_ROLES,
)
from app.models import Department, Profile
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentOut
from app.services.reference_data_cache import invalidate_department_names

router = APIRouter(
    prefix="/departments",
    tags=["Departments"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=DepartmentOut, dependencies=[Depends(require_admin)])
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = payload.model_dump()
    if data.get("warehouse_id") is None and scoped_warehouse_id(current_user):
        data["warehouse_id"] = scoped_warehouse_id(current_user)
    assert_in_active_warehouse(current_user, data.get("warehouse_id"), "Warehouse")
    obj = Department(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    invalidate_department_names()
    return obj


@router.get("/", response_model=list[DepartmentOut])
def list_departments(
    warehouse_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    q = db.query(Department)
    # For admins/super_admins, pin to their active warehouse (overriding any
    # client-supplied warehouse_id). Non-admin users keep the existing behaviour
    # so ticket-creation dropdowns aren't broken.
    if _role_of(current_user) in ADMIN_ROLES:
        scoped_wh = active_warehouse_id(current_user)
        if scoped_wh:
            warehouse_id = scoped_wh
    if warehouse_id:
        q = q.filter(Department.warehouse_id == warehouse_id)
    return q.order_by(Department.name).all()


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(department_id: str, db: Session = Depends(get_db)):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")
    return obj


@router.put("/{department_id}", response_model=DepartmentOut, dependencies=[Depends(require_admin)])
def update_department(
    department_id: str,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_in_active_warehouse(current_user, obj.warehouse_id, "Department")
    changes = payload.model_dump(exclude_unset=True)
    if "warehouse_id" in changes:
        assert_in_active_warehouse(current_user, changes["warehouse_id"], "Warehouse")

    for key, value in changes.items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    invalidate_department_names()
    return obj


@router.delete("/{department_id}", dependencies=[Depends(require_admin)])
def delete_department(
    department_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")
    assert_in_active_warehouse(current_user, obj.warehouse_id, "Department")
    db.delete(obj)
    db.commit()
    invalidate_department_names()
    return {"message": "Department deleted"}