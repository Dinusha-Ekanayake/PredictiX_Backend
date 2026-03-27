from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import AssetDocument
from app.schemas.misc import AssetDocumentCreate, AssetDocumentOut

router = APIRouter(prefix="/asset-documents", tags=["Asset Documents"])


@router.post("/", response_model=AssetDocumentOut)
def create_asset_document(payload: AssetDocumentCreate, db: Session = Depends(get_db)):
    obj = AssetDocument(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetDocumentOut])
def list_asset_documents(
    asset_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(AssetDocument)
    if asset_id:
        q = q.filter(AssetDocument.asset_id == asset_id)
    return q.order_by(AssetDocument.created_at.desc()).all()


@router.delete("/{document_id}")
def delete_asset_document(document_id: str, db: Session = Depends(get_db)):
    obj = db.query(AssetDocument).filter(AssetDocument.id == document_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset document not found")
    db.delete(obj)
    db.commit()
    return {"message": "Asset document deleted"}