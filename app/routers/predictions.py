from fastapi import APIRouter, HTTPException

from app.schemas.prediction import (
    PredictionRequest,
    ClassificationResponse,
    RegressionResponse,
    HealthScoreResponse,
    FullPredictionResponse,
    HealthResponse,
    DebugFeaturesResponse,
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