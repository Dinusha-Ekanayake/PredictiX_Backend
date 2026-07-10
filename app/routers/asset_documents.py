from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_admin, require_user
from app.models import Asset, AssetDocument
from app.schemas.misc import AssetDocumentCreate, AssetDocumentOut

router = APIRouter(
    prefix="/asset-documents",
    tags=["Asset Documents"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=AssetDocumentOut, dependencies=[Depends(require_admin)])
def create_asset_document(payload: AssetDocumentCreate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj = AssetDocument(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetDocumentOut])
def list_asset_documents(
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(AssetDocument)
    if asset_id:
        q = q.filter(AssetDocument.asset_id == asset_id)
    return q.order_by(AssetDocument.created_at.desc()).offset(offset).limit(limit).all()


@router.delete("/{document_id}", dependencies=[Depends(require_admin)])
def delete_asset_document(document_id: str, db: Session = Depends(get_db)):
    obj = db.query(AssetDocument).filter(AssetDocument.id == document_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset document not found")
    db.delete(obj)
    db.commit()
    return {"message": "Asset document deleted"}