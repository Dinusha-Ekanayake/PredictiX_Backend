from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user
from app.models import ModelRegistry
from app.schemas.misc import ModelRegistryCreate, ModelRegistryOut

router = APIRouter(
    prefix="/model-registry",
    tags=["Model Registry"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=ModelRegistryOut, dependencies=[Depends(require_admin)])
def create_model_registry(payload: ModelRegistryCreate, db: Session = Depends(get_db)):
    obj = ModelRegistry(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[ModelRegistryOut])
def list_model_registry(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return db.query(ModelRegistry).order_by(ModelRegistry.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{model_id}", response_model=ModelRegistryOut)
def get_model_registry(model_id: str, db: Session = Depends(get_db)):
    obj = db.query(ModelRegistry).filter(ModelRegistry.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Model not found")
    return obj