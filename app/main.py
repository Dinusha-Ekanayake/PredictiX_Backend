# from contextlib import asynccontextmanager
# from pathlib import Path
# import pickle
# import os

# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from .routers import auth

# # existing routers
# from .routers.assets import router as assets_router
# from .routers.predictions import router as predictions_router
# from .routers.warehouse_dashboard import warehouse_dashboard_router
# from .routers.vehicle_predictions import router as vehicle_predictions_router

# # additional routers created for DB endpoints
# from .routers.warehouses import router as warehouses_router
# from .routers.departments import router as departments_router
# from .routers.profile import router as profiles_router
# from .routers.maintenance import router as maintenance_router
# from .routers.tickets import router as tickets_router
# from .routers.sensor_readings import router as sensor_readings_router
# from .routers.reports import router as reports_router
# from .routers.notifications import router as notifications_router
# from .routers.asset_assignments import router as asset_assignments_router
# from .routers.asset_status_history import router as asset_status_history_router
# from .routers.asset_documents import router as asset_documents_router
# from .routers.ticket_comments import router as ticket_comments_router
# from .routers.ticket_attachments import router as ticket_attachments_router
# from .routers.ticket_status_history import router as ticket_status_history_router
# from .routers.model_registry import router as model_registry_router
# from .routers.prediction_explanations import router as prediction_explanations_router
# from .routers.report_sources import router as report_sources_router
# from .routers.user_notification_preferences import router as user_notification_preferences_router
# from .routers.db_debug import router as db_debug_router
# from .routers.user_profile import router as user_profile_router
# from .routers.asset_summaries import router as asset_summaries_router

# from app.ai.services.ticket_categorization_service import warmup_ticket_categorizer
# from app.ai.services.asset_summary_service import warmup_asset_summary_model

# BASE_DIR = Path(__file__).resolve().parent
# MODEL_DIR = BASE_DIR / "ai" / "models"

# CLF_MODEL_PATH = MODEL_DIR / "pdm_classifier_model" / "predictive_maintenance_model.pkl"
# CLF_FEATURES_PATH = MODEL_DIR / "pdm_classifier_model" / "maintenance_classifier_features.pkl"

# REG_MODEL_PATH = MODEL_DIR / "pdm_regressor_model" / "days_until_next_maintenance_regressor.pkl"
# REG_FEATURES_PATH = MODEL_DIR / "pdm_regressor_model" / "regression_selected_features.pkl"

# clf_model = None
# clf_features = None
# reg_model = None
# reg_features = None


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     global clf_model, clf_features, reg_model, reg_features

#     try:
#         with open(CLF_MODEL_PATH, "rb") as f:
#             clf_model = pickle.load(f)

#         with open(CLF_FEATURES_PATH, "rb") as f:
#             clf_features = pickle.load(f)

#         with open(REG_MODEL_PATH, "rb") as f:
#             reg_model = pickle.load(f)

#         with open(REG_FEATURES_PATH, "rb") as f:
#             reg_features = pickle.load(f)

#         if hasattr(clf_model, "feature_names_") and clf_model.feature_names_:
#             clf_features = list(clf_model.feature_names_)

#         if hasattr(reg_model, "feature_names_") and reg_model.feature_names_:
#             reg_features = list(reg_model.feature_names_)

#         print("PredictiX local PdM models loaded successfully.")
#         print("Classifier features:", clf_features)
#         print("Regressor features:", reg_features)

#     except Exception as e:
#         print(f"Local PdM model loading failed: {e}")
#         raise RuntimeError(f"Failed to load local PdM models: {e}") from e

#     if os.getenv("DISABLE_HF_MODELS", "false").lower() != "true":
#         try:
#             warmup_ticket_categorizer()
#             print("Ticket categorization model loaded successfully from Hugging Face.")
#         except Exception as e:
#             print(f"Ticket categorization model loading failed: {e}")
#             raise RuntimeError(f"Failed to load ticket categorization model: {e}") from e

#         try:
#             warmup_asset_summary_model()
#             print("Asset summary model loaded successfully from Hugging Face.")
#         except Exception as e:
#             print(f"Asset summary model loading failed: {e}")
#             raise RuntimeError(f"Failed to load asset summary model: {e}") from e
#     else:
#         print("HuggingFace models disabled (DISABLE_HF_MODELS=true). Skipping warmup.")

#     yield

#     print("Shutting down PredictiX API...")


# app = FastAPI(
#     title="PredictiX API",
#     version="1.0",
#     lifespan=lifespan,
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://localhost:3000",
#         "http://127.0.0.1:3000",
#         "http://localhost:3001",
#         "http://127.0.0.1:3001",
#         "http://localhost:5173",
#         "http://127.0.0.1:5173",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # auth
# # app.include_router(auth.router)  # DISABLED - Using inline /auth/login in main.py instead
# # print(f"[MAIN] Auth router included. Routes in auth.router: {[r.path for r in auth.router.routes]}")

# # existing feature routers
# app.include_router(assets_router)
# app.include_router(predictions_router)
# app.include_router(vehicle_predictions_router)
# app.include_router(warehouse_dashboard_router)

# # database CRUD / listing routers
# app.include_router(warehouses_router)
# app.include_router(departments_router)
# app.include_router(profiles_router)
# app.include_router(maintenance_router)
# app.include_router(tickets_router)
# app.include_router(sensor_readings_router)
# app.include_router(reports_router)
# app.include_router(notifications_router)

# # remaining schema routers
# app.include_router(asset_assignments_router)
# app.include_router(asset_status_history_router)
# app.include_router(asset_documents_router)
# app.include_router(ticket_comments_router)
# app.include_router(ticket_attachments_router)
# app.include_router(ticket_status_history_router)
# app.include_router(model_registry_router)
# app.include_router(prediction_explanations_router)
# app.include_router(report_sources_router)
# app.include_router(user_notification_preferences_router)
# app.include_router(db_debug_router)
# app.include_router(user_profile_router)
# app.include_router(asset_summaries_router)


# @app.get("/")
# def home():
#     return {
#         "message": "PredictiX API running",
#         "models_loaded": all([
#             clf_model is not None,
#             clf_features is not None,
#             reg_model is not None,
#             reg_features is not None,
#         ]),
#     }


# @app.post("/auth/login")
# def login_endpoint(request_data: dict):
#     from datetime import datetime, timedelta
#     from jose import jwt
#     import uuid
    
#     email = request_data.get("email", "").strip().lower()
#     password = request_data.get("password", "").strip()
#     role = request_data.get("role", "").upper()
    
#     TEST_USERS = {
#         "nuwan.gunasekara.tra1@lankalogix.lk": {"password": "user", "full_name": "Nuwan Gunasekara", "role": "user"},
#         "anjali.warnakulasuriya.adm1@lankalogix.lk": {"password": "admin", "full_name": "Anjali Warnakulasuriya", "role": "admin"}
#     }
    
#     if email not in TEST_USERS or TEST_USERS[email]["password"] != password:
#         from fastapi import HTTPException
#         raise HTTPException(status_code=401, detail="Invalid credentials")
    
#     user_data = TEST_USERS[email]
#     if user_data["role"].upper() != role:
#         from fastapi import HTTPException
#         raise HTTPException(status_code=401, detail="Invalid role")
    
#     # Get the real user from database
#     from app.db import SessionLocal
#     from app.models import Profile
#     db = SessionLocal()
#     user = db.query(Profile).filter(Profile.email == email).first()
    
#     if user:
#         user_id = str(user.id)
#         print(f"[LOGIN] Found user in DB: {user_id}")
#     else:
#         # Fallback to generated UUID if user not in DB
#         user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
#         print(f"[LOGIN] User not in DB, using generated ID: {user_id}")
    
#     db.close()
    
#     # Create JWT payload
#     payload = {
#         "sub": user_id,
#         "email": email,
#         "role": user_data["role"],
#         "exp": datetime.utcnow() + timedelta(hours=24)
#     }
    
#     # Use JWT_SECRET from .env file
#     secret = os.getenv("JWT_SECRET", "supersecret")
#     algorithm = os.getenv("JWT_ALGORITHM", "HS256")
#     token = jwt.encode(payload, secret, algorithm=algorithm)
    
#     print(f"[LOGIN] Generated token for {email} with user_id={user_id}")
    
#     return {
#         "access_token": token,
#         "token_type": "bearer",
#         "user_id": user_id,
#         "email": email,
#         "role": user_data["role"],
#         "full_name": user_data["full_name"]
#     }


# @app.get("/favicon.ico", include_in_schema=False)
# def favicon():
#     return {}

from contextlib import asynccontextmanager
from pathlib import Path
import pickle
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth

# existing routers
from .routers.assets import router as assets_router
from .routers.predictions import router as predictions_router
from .routers.warehouse_dashboard import warehouse_dashboard_router
from .routers.vehicle_predictions import router as vehicle_predictions_router

# additional routers created for DB endpoints
from .routers.warehouses import router as warehouses_router
from .routers.departments import router as departments_router
from .routers.profile import router as profiles_router
from .routers.maintenance import router as maintenance_router
from .routers.tickets import router as tickets_router
from .routers.sensor_readings import router as sensor_readings_router
from .routers.reports import router as reports_router
from .routers.notifications import router as notifications_router
from .routers.asset_assignments import router as asset_assignments_router
from .routers.asset_status_history import router as asset_status_history_router
from .routers.asset_documents import router as asset_documents_router
from .routers.ticket_comments import router as ticket_comments_router
from .routers.ticket_attachments import router as ticket_attachments_router
from .routers.ticket_status_history import router as ticket_status_history_router
from .routers.model_registry import router as model_registry_router
from .routers.prediction_explanations import router as prediction_explanations_router
from .routers.report_sources import router as report_sources_router
from .routers.user_notification_preferences import router as user_notification_preferences_router
from .routers.db_debug import router as db_debug_router
from .routers.user_profile import router as user_profile_router
from .routers.asset_summaries import router as asset_summaries_router

from app.ai.services.ticket_categorization_service import warmup_ticket_categorizer
from app.ai.services.asset_summary_service import warmup_asset_summary_model

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "ai" / "models"

CLF_MODEL_PATH    = MODEL_DIR / "pdm_classifier_model" / "predictive_maintenance_model.pkl"
CLF_FEATURES_PATH = MODEL_DIR / "pdm_classifier_model" / "maintenance_classifier_features.pkl"
REG_MODEL_PATH    = MODEL_DIR / "pdm_regressor_model"  / "days_until_next_maintenance_regressor.pkl"
REG_FEATURES_PATH = MODEL_DIR / "pdm_regressor_model"  / "regression_selected_features.pkl"

clf_model    = None
clf_features = None
reg_model    = None
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

        print("PredictiX local PdM models loaded successfully.")
        print("Classifier features:", clf_features)
        print("Regressor features:", reg_features)

    except Exception as e:
        print(f"Local PdM model loading failed: {e}")
        raise RuntimeError(f"Failed to load local PdM models: {e}") from e

    if os.getenv("DISABLE_HF_MODELS", "false").lower() != "true":
        try:
            warmup_ticket_categorizer()
            print("Ticket categorization model loaded successfully from Hugging Face.")
        except Exception as e:
            print(f"Ticket categorization model loading failed: {e}")
            raise RuntimeError(f"Failed to load ticket categorization model: {e}") from e

        try:
            warmup_asset_summary_model()
            print("Asset summary model loaded successfully from Hugging Face.")
        except Exception as e:
            print(f"Asset summary model loading failed: {e}")
            raise RuntimeError(f"Failed to load asset summary model: {e}") from e
    else:
        print("HuggingFace models disabled (DISABLE_HF_MODELS=true). Skipping warmup.")

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
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# auth router — handles POST /auth/login and GET /auth/test
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
app.include_router(user_profile_router)
app.include_router(asset_summaries_router)


@app.get("/")
def home():
    return {
        "message": "PredictiX API running",
        "models_loaded": all([
            clf_model    is not None,
            clf_features is not None,
            reg_model    is not None,
            reg_features is not None,
        ]),
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}