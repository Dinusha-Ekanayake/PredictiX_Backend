from contextlib import asynccontextmanager
from pathlib import Path
import pickle

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth

# existing routers
from app.routers.assets import router as assets_router
from app.routers.predictions import router as predictions_router
from app.routers.warehouse_dashboard import warehouse_dashboard_router
from app.routers.vehicle_predictions import router as vehicle_predictions_router

# additional routers created for DB endpoints
from app.routers.warehouses import router as warehouses_router
from app.routers.departments import router as departments_router
from app.routers.profile import router as profiles_router
from app.routers.maintenance import router as maintenance_router
from app.routers.tickets import router as tickets_router
from app.routers.sensor_readings import router as sensor_readings_router
from app.routers.reports import router as reports_router
from app.routers.notifications import router as notifications_router
from app.routers.asset_assignments import router as asset_assignments_router
from app.routers.asset_status_history import router as asset_status_history_router
from app.routers.asset_documents import router as asset_documents_router
from app.routers.ticket_comments import router as ticket_comments_router
from app.routers.ticket_attachments import router as ticket_attachments_router
from app.routers.ticket_status_history import router as ticket_status_history_router
from app.routers.model_registry import router as model_registry_router
from app.routers.prediction_explanations import router as prediction_explanations_router
from app.routers.report_sources import router as report_sources_router
from app.routers.user_notification_preferences import router as user_notification_preferences_router
from app.routers.db_debug import router as db_debug_router


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
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# auth
app.include_router(auth.router)

# existing feature routers
app.include_router(assets_router)
app.include_router(predictions_router)
app.include_router(vehicle_predictions_router)
app.include_router(warehouse_dashboard_router)

# database CRUD / listing routers
app.include_router(warehouses_router)
app.include_router(departments_router)
app.include_router(profiles_router)
app.include_router(maintenance_router)
app.include_router(tickets_router)
app.include_router(sensor_readings_router)
app.include_router(reports_router)
app.include_router(notifications_router)

# remaining schema routers
app.include_router(asset_assignments_router)
app.include_router(asset_status_history_router)
app.include_router(asset_documents_router)
app.include_router(ticket_comments_router)
app.include_router(ticket_attachments_router)
app.include_router(ticket_status_history_router)
app.include_router(model_registry_router)
app.include_router(prediction_explanations_router)
app.include_router(report_sources_router)
app.include_router(user_notification_preferences_router)
app.include_router(db_debug_router)


@app.get("/")
def home():
    return {
        "message": "PredictiX API running",
        "models_loaded": all([
            clf_model is not None,
            clf_features is not None,
            reg_model is not None,
            reg_features is not None,
        ]),
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}