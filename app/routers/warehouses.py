from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user
from app.models import Warehouse
from app.schemas.warehouse import WarehouseCreate, WarehouseOut

router = APIRouter(
    prefix="/warehouses",
    tags=["Warehouses"],
    dependencies=[Depends(require_user)],
)

@router.post("/", response_model=WarehouseOut, dependencies=[Depends(require_admin)])
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db)):
    obj = Warehouse(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@router.get("/", response_model=list[WarehouseOut])
def list_warehouses(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return db.query(Warehouse).order_by(Warehouse.name).offset(offset).limit(limit).all()

@router.get("/{warehouse_id}", response_model=WarehouseOut)
def get_warehouse(warehouse_id: str, db: Session = Depends(get_db)):
    obj = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return obj