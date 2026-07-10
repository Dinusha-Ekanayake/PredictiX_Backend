from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db, require_user
from app.models import PredictionExplanation, PredictionFeatureImportance, PredictionRun
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


@router.post("/", response_model=PredictionExplanationOut)
def create_prediction_explanation(payload: PredictionExplanationCreate, db: Session = Depends(get_db)):
    run = db.query(PredictionRun).filter(PredictionRun.id == payload.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Prediction run not found")

    obj = PredictionExplanation(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=list[PredictionExplanationOut])
def list_prediction_explanations(
    run_id: str | None = Query(default=None),
    asset_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(PredictionExplanation)
    if run_id:
        q = q.filter(PredictionExplanation.run_id == run_id)
    if asset_id:
        q = q.filter(PredictionExplanation.asset_id == asset_id)
    return q.order_by(PredictionExplanation.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/feature-importance", response_model=PredictionFeatureImportanceOut)
def create_prediction_feature_importance(payload: PredictionFeatureImportanceCreate, db: Session = Depends(get_db)):
    explanation = db.query(PredictionExplanation).filter(PredictionExplanation.id == payload.explanation_id).first()
    if not explanation:
        raise HTTPException(status_code=404, detail="Prediction explanation not found")

    obj = PredictionFeatureImportance(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/feature-importance", response_model=list[PredictionFeatureImportanceOut])
def list_prediction_feature_importance(
    explanation_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(PredictionFeatureImportance)
    if explanation_id:
        q = q.filter(PredictionFeatureImportance.explanation_id == explanation_id)
    return q.order_by(PredictionFeatureImportance.rank_order.asc()).offset(offset).limit(limit).all()