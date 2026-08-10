from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.deps import (
    get_db,
    get_current_user,
    require_user,
    require_admin,
    assert_asset_in_scope,
    user_can_view_asset,
    is_admin_role,
    active_warehouse_id,
)
from app.models import Asset, PredictionExplanation, PredictionFeatureImportance, PredictionRun, Profile
from app.schemas.misc import (
    PredictionExplanationCreate,
    PredictionExplanationOut,
    PredictionFeatureImportanceCreate,
    PredictionFeatureImportanceOut,
)

router = APIRouter(
    prefix="/prediction-explanations",
    tags=["Prediction Explanations"],
    dependencies=[Depends(require_user)],
)


@router.post(
    "/", response_model=PredictionExplanationOut, dependencies=[Depends(require_admin)],
    deprecated=True,
    summary="[No real writer] Log a prediction explanation",
)
def create_prediction_explanation(payload: PredictionExplanationCreate, db: Session = Depends(get_db)):
    """Admin-only: this table is meant to be populated by the real
    inference pipeline's SHAP output, not submitted by a client. Previously
    gated only by require_user, any authenticated low-privilege account
    could insert arbitrary explanation_text attributed to any real run_id
    — a fabricated "AI explanation" an admin might later trust.

    Confirmed no real writer exists — the actual SHAP/inference pipeline
    never calls this (same root cause as the earlier-fixed dead-table
    finding elsewhere in this codebase). Verified this isn't a broken link:
    grepped the frontend for prediction_explanations/explanation_text/
    feature_name/rank_order — the only hit is a plain UI text label in
    WarehouseAIReportPanel.tsx describing a data source name, not an API
    call. Left live and fully functional rather than removed, in case a
    real writer is wired up later."""
    run = db.query(PredictionRun).filter(PredictionRun.id == payload.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Prediction run not found")

    obj = PredictionExplanation(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/", response_model=list[PredictionExplanationOut],
    deprecated=True,
    summary="[No real writer] List prediction explanations",
)
def list_prediction_explanations(
    run_id: UUID | None = Query(default=None),
    asset_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    if asset_id:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        if is_admin_role(current_user):
            assert_asset_in_scope(asset, current_user)
        elif not user_can_view_asset(asset, current_user):
            raise HTTPException(status_code=404, detail="Asset not found")

    # Scope by the linked asset's warehouse even when querying by run_id
    # alone (or with no filter at all) — previously unscoped in both cases,
    # letting any authenticated user read explanations across every
    # warehouse by omitting asset_id or supplying any run_id.
    q = db.query(PredictionExplanation).outerjoin(Asset, Asset.id == PredictionExplanation.asset_id)
    if is_admin_role(current_user):
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            q = q.filter(or_(Asset.warehouse_id == wh_id, PredictionExplanation.asset_id.is_(None)))
    else:
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        conditions = [Asset.assigned_to == uid]
        if user_wh_id:
            conditions.append(Asset.warehouse_id == user_wh_id)
        q = q.filter(or_(*conditions))

    if run_id:
        q = q.filter(PredictionExplanation.run_id == run_id)
    if asset_id:
        q = q.filter(PredictionExplanation.asset_id == asset_id)
    return q.order_by(PredictionExplanation.created_at.desc()).offset(offset).limit(limit).all()


@router.post(
    "/feature-importance", response_model=PredictionFeatureImportanceOut, dependencies=[Depends(require_admin)],
    deprecated=True,
    summary="[No real writer] Log prediction feature importance",
)
def create_prediction_feature_importance(payload: PredictionFeatureImportanceCreate, db: Session = Depends(get_db)):
    """Admin-only — see create_prediction_explanation above. Same "no real
    writer, not a broken link" finding applies here."""
    explanation = db.query(PredictionExplanation).filter(PredictionExplanation.id == payload.explanation_id).first()
    if not explanation:
        raise HTTPException(status_code=404, detail="Prediction explanation not found")

    obj = PredictionFeatureImportance(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get(
    "/feature-importance", response_model=list[PredictionFeatureImportanceOut],
    deprecated=True,
    summary="[No real writer] List prediction feature importance",
)
def list_prediction_feature_importance(
    explanation_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    # Previously had no scoping at all. Join through the parent explanation
    # to its linked asset, same warehouse/ownership rule as the list above.
    q = (
        db.query(PredictionFeatureImportance)
        .join(PredictionExplanation, PredictionExplanation.id == PredictionFeatureImportance.explanation_id)
        .outerjoin(Asset, Asset.id == PredictionExplanation.asset_id)
    )
    if is_admin_role(current_user):
        wh_id = active_warehouse_id(current_user)
        if wh_id:
            q = q.filter(or_(Asset.warehouse_id == wh_id, PredictionExplanation.asset_id.is_(None)))
    else:
        uid = str(getattr(current_user, "id", ""))
        user_wh_id = getattr(current_user, "warehouse_id", None)
        conditions = [Asset.assigned_to == uid]
        if user_wh_id:
            conditions.append(Asset.warehouse_id == user_wh_id)
        q = q.filter(or_(*conditions))

    if explanation_id:
        q = q.filter(PredictionFeatureImportance.explanation_id == explanation_id)
    return q.order_by(PredictionFeatureImportance.rank_order.asc()).offset(offset).limit(limit).all()