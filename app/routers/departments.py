from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import Department
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentOut

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post("/", response_model=DepartmentOut)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)):
    obj = Department(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[DepartmentOut])
def list_departments(
    warehouse_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(Department)
    if warehouse_id:
        q = q.filter(Department.warehouse_id == warehouse_id)
    return q.order_by(Department.name).all()


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(department_id: str, db: Session = Depends(get_db)):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")
    return obj


@router.put("/{department_id}", response_model=DepartmentOut)
def update_department(department_id: str, payload: DepartmentUpdate, db: Session = Depends(get_db)):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{department_id}")
def delete_department(department_id: str, db: Session = Depends(get_db)):
    obj = db.query(Department).filter(Department.id == department_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(obj)
    db.commit()
    return {"message": "Department deleted"}