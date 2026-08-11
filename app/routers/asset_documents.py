from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from app.deps import (
    get_db,
    get_current_user,
    is_admin_role,
    require_admin,
    require_user,
    assert_asset_in_scope,
    active_warehouse_id,
)
from app.models import Asset, AssetDocument, Profile
from app.schemas.misc import AssetDocumentCreate, AssetDocumentOut

router = APIRouter(
    prefix="/asset-documents",
    tags=["Asset Documents"],
    dependencies=[Depends(require_user)],
)


@router.post("/", response_model=AssetDocumentOut, dependencies=[Depends(require_admin)])
def create_asset_document(
    payload: AssetDocumentCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    # Previously had no warehouse check on the target asset, and
    # uploaded_by was taken verbatim from the client instead of the
    # authenticated session — any admin could attach a document to another
    # warehouse's asset and attribute the upload to an arbitrary user.
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

    data = payload.model_dump()
    data["uploaded_by"] = current_user.id
    obj = AssetDocument(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[AssetDocumentOut])
def list_asset_documents(
    asset_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = db.query(AssetDocument)

    # Same rule as maintenance.py's list scoping — a regular user only sees
    # documents for assets assigned to them, not the whole fleet. Admins
    # are scoped to their active warehouse — previously unscoped, so any
    # admin saw every warehouse's document metadata.
    if not is_admin_role(current_user):
        uid = str(getattr(current_user, "id", ""))
        q = q.join(Asset, AssetDocument.asset_id == Asset.id).filter(
            cast(Asset.assigned_to, String) == uid
        )
    else:
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            q = q.join(Asset, AssetDocument.asset_id == Asset.id).filter(Asset.warehouse_id == wh_id)

    if asset_id:
        q = q.filter(AssetDocument.asset_id == asset_id)
    return q.order_by(AssetDocument.created_at.desc()).offset(offset).limit(limit).all()


@router.delete("/{document_id}", dependencies=[Depends(require_admin)])
def delete_asset_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    obj = db.query(AssetDocument).filter(AssetDocument.id == document_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Asset document not found")
    # Previously unscoped — any admin could delete any warehouse's
    # document metadata row by ID.
    asset = db.query(Asset).filter(Asset.id == obj.asset_id).first()
    if asset is not None:
        assert_asset_in_scope(asset, current_user)
    db.delete(obj)
    db.commit()
    return {"message": "Asset document deleted"}