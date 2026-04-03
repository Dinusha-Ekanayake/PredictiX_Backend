from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import (
    PredictionRun,
    AssetFailurePrediction,
    AssetCostPrediction,
    TicketPrediction,
)
from app.schemas.prediction import (
    PredictionRequest,
    ClassificationResponse,
    RegressionResponse,
    HealthScoreResponse,
    FullPredictionResponse,
    HealthResponse,
    DebugFeaturesResponse,
    PredictionRunOut,
    AssetFailurePredictionOut,
    AssetCostPredictionOut,
    TicketPredictionOut,
)
from app.ai.services.prediction_service import (
    run_classification,
    run_regression,
    run_health_score,
    run_full_prediction,
)

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("/health", response_model=HealthResponse)
def prediction_health():
    from app.main import clf_model, clf_features, reg_model, reg_features

    return {
        "status": "ok",
        "models_loaded": all([
            clf_model is not None,
            clf_features is not None,
            reg_model is not None,
            reg_features is not None,
        ]),
    }


@router.get("/debug/features", response_model=DebugFeaturesResponse)
def debug_features():
    from app.main import clf_features, reg_features

    return {
        "classifier_features": clf_features or [],
        "regressor_features": reg_features or [],
        "regressor_categorical_features": ["vehicle_role"],
    }


@router.post("/classification", response_model=ClassificationResponse)
def classification(payload: PredictionRequest):
    from app.main import clf_model, clf_features

    if clf_model is None:
        raise HTTPException(status_code=500, detail="Classification model is not loaded")

    data = payload.model_dump()
    return run_classification(data, clf_model, clf_features)


@router.post("/regression", response_model=RegressionResponse)
def regression(payload: PredictionRequest):
    from app.main import reg_model, reg_features

    if reg_model is None:
        raise HTTPException(status_code=500, detail="Regression model is not loaded")

    data = payload.model_dump()
    return run_regression(data, reg_model, reg_features)


@router.post("/health-score", response_model=HealthScoreResponse)
def health_score(payload: PredictionRequest):
    data = payload.model_dump()
    return run_health_score(data)


@router.post("/full", response_model=FullPredictionResponse)
def full_prediction(payload: PredictionRequest):
    from app.main import clf_model, clf_features, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=500, detail="Models are not loaded")

    data = payload.model_dump()
    return run_full_prediction(
        data=data,
        clf_model=clf_model,
        clf_features=clf_features,
        reg_model=reg_model,
        reg_features=reg_features,
    )


@router.get("/runs", response_model=list[PredictionRunOut])
def list_prediction_runs(db: Session = Depends(get_db)):
    return db.query(PredictionRun).order_by(PredictionRun.run_started_at.desc()).all()


@router.get("/runs/{run_id}", response_model=PredictionRunOut)
def get_prediction_run(run_id: str, db: Session = Depends(get_db)):
    row = db.query(PredictionRun).filter(PredictionRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prediction run not found")
    return row


@router.get("/failure/{asset_id}", response_model=AssetFailurePredictionOut)
def get_latest_failure_prediction(asset_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(AssetFailurePrediction)
        .filter(AssetFailurePrediction.asset_id == asset_id)
        .order_by(AssetFailurePrediction.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No failure prediction found")
    return row


@router.get("/failure/run/{run_id}", response_model=AssetFailurePredictionOut)
def get_failure_prediction_by_run(run_id: str, db: Session = Depends(get_db)):
    row = db.query(AssetFailurePrediction).filter(AssetFailurePrediction.run_id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Failure prediction not found")
    return row


@router.get("/cost/{asset_id}", response_model=AssetCostPredictionOut)
def get_latest_cost_prediction(asset_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(AssetCostPrediction)
        .filter(AssetCostPrediction.asset_id == asset_id)
        .order_by(AssetCostPrediction.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No cost prediction found")
    return row


@router.get("/cost/run/{run_id}", response_model=AssetCostPredictionOut)
def get_cost_prediction_by_run(run_id: str, db: Session = Depends(get_db)):
    row = db.query(AssetCostPrediction).filter(AssetCostPrediction.run_id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cost prediction not found")
    return row


@router.get("/ticket/{ticket_id}", response_model=TicketPredictionOut)
def get_ticket_prediction(ticket_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(TicketPrediction)
        .filter(TicketPrediction.ticket_id == ticket_id)
        .order_by(TicketPrediction.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Ticket prediction not found")
    return row