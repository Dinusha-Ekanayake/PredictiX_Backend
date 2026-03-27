from contextlib import asynccontextmanager
from pathlib import Path
import pickle

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth
from app.routers.assets import router as assets_router
from app.routers.predictions import router as predictions_router
from app.routers.vehicle_predictions import router as vehicle_predictions_router




BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "ai" / "models"

CLF_MODEL_PATH = MODEL_DIR / "pdm_classifier_model" / "predictive_maintenance_model.pkl"
CLF_FEATURES_PATH = MODEL_DIR / "pdm_classifier_model" / "maintenance_classifier_features.pkl"

REG_MODEL_PATH = MODEL_DIR / "pdm_regressor_model" / "days_until_next_maintenance_regressor.pkl"
REG_FEATURES_PATH = MODEL_DIR / "pdm_regressor_model" / "regression_selected_features.pkl"

clf_model = None
clf_features = None
reg_model = None
reg_features = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global clf_model, clf_features, reg_model, reg_features

    try:
        with open(CLF_MODEL_PATH, "rb") as f:
            clf_model = pickle.load(f)

        with open(CLF_FEATURES_PATH, "rb") as f:
            clf_features = pickle.load(f)

        with open(REG_MODEL_PATH, "rb") as f:
            reg_model = pickle.load(f)

        with open(REG_FEATURES_PATH, "rb") as f:
            reg_features = pickle.load(f)

        if hasattr(clf_model, "feature_names_") and clf_model.feature_names_:
            clf_features = list(clf_model.feature_names_)

        if hasattr(reg_model, "feature_names_") and reg_model.feature_names_:
            reg_features = list(reg_model.feature_names_)

        print("PredictiX models loaded successfully.")
        print("Classifier features:", clf_features)
        print("Regressor features:", reg_features)

    except Exception as e:
        print(f"Model loading failed: {e}")
        raise RuntimeError(f"Failed to load models: {e}") from e

    yield

    print("Shutting down PredictiX API...")


app = FastAPI(
    title="PredictiX API",
    version="1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(assets_router)
app.include_router(predictions_router)
app.include_router(vehicle_predictions_router)


@app.get("/")
def home():
    return {"message": "PredictiX API running"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}