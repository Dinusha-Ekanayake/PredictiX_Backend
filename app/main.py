"""PredictiX API — FastAPI application entry point."""
from __future__ import annotations

import joblib
import logging
import os
import pickle
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ─── Routers ──────────────────────────────────────────────────────────────────
from .routers.admin_dashboard import admin_dashboard_router
from .routers.chatbot import router as chatbot_router
from .routers.faqs import router as faqs_router
from .routers.asset_assignments import router as asset_assignments_router
from .routers.asset_documents import router as asset_documents_router
from .routers.asset_status_history import router as asset_status_history_router
from .routers.asset_summaries import router as asset_summaries_router
from .routers.assets import router as assets_router
from .routers.auth import router as auth_router
from .routers.db_debug import router as db_debug_router
from .routers.departments import router as departments_router
from .routers.maintenance import router as maintenance_router
from .routers.model_registry import router as model_registry_router
from .routers.notifications import router as notifications_router
from .routers.prediction_explanations import router as prediction_explanations_router
from .routers.predictions import router as predictions_router
from .routers.profile import router as profiles_router
from .routers.report_sources import router as report_sources_router
from .routers.reports import router as reports_router
from .routers.sensor_readings import router as sensor_readings_router
from .routers.ticket_attachments import router as ticket_attachments_router
from .routers.ticket_comments import router as ticket_comments_router
from .routers.ticket_status_history import router as ticket_status_history_router
from .routers.tickets import router as tickets_router
from .routers.notification_preferences import router as notification_preferences_router
from .routers.users import router as users_router
from .routers.vehicle_predictions import router as vehicle_predictions_router
from .routers.warehouse_dashboard import warehouse_dashboard_router
from .routers.warehouses import router as warehouses_router
from .routers.batch_predictions import router as batch_predictions_router
from .routers.websockets import router as websockets_router

# Sharada — user-role self-service profile (/user-profile)
from .routers.user_profile import router as user_profile_router
# Sharada — user-role ticket section (/user/tickets)
from .routers.user_tickets import router as user_tickets_router
# Sharada — FRSO warehouse-level survival predictions (/survival/*)
from .routers.survival_predictions import router as survival_predictions_router

# ─── ML warmup ────────────────────────────────────────────────────────────────
from app.ai.services.asset_summary_service import warmup_asset_summary_model
from app.ai.services.ticket_categorization_service import warmup_ticket_categorizer
from app.ai.services.ticket_priority_service import warmup_ticket_priority

log = logging.getLogger("predictix")

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "ai" / "models"

CLF_MODEL_PATH    = MODEL_DIR / "pdm_classifier_model" / "predictive_maintenance_model.pkl"
CLF_FEATURES_PATH = MODEL_DIR / "pdm_classifier_model" / "maintenance_classifier_features.pkl"
REG_MODEL_PATH    = MODEL_DIR / "pdm_regressor_model"  / "days_until_next_maintenance_regressor.pkl"
REG_FEATURES_PATH = MODEL_DIR / "pdm_regressor_model"  / "regression_selected_features.pkl"

clf_model = None
clf_features: list = []
clf_threshold: float = 0.5
clf_categorical_cols: list = []
reg_model = None
reg_features: list = []

scheduler: BackgroundScheduler | None = None
_model_load_lock = __import__('threading').Lock()


def _load_pickle(path: Path):
    with open(path, "rb") as fh:
        return pickle.load(fh)


def _load_pdm_models():
    """Lazily load heavy PdM models (thread-safe, idempotent)."""
    global clf_model, clf_features, clf_threshold, clf_categorical_cols, reg_model, reg_features
    if clf_model is not None and reg_model is not None:
        return

    with _model_load_lock:
        if clf_model is not None and reg_model is not None:
            return
        try:
            clf_model    = _load_pickle(CLF_MODEL_PATH)
            clf_features = _load_pickle(CLF_FEATURES_PATH)
            if getattr(clf_model, "feature_names_", None):
                clf_features = list(clf_model.feature_names_)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                reg_model = _load_pickle(REG_MODEL_PATH)
            reg_features = _load_pickle(REG_FEATURES_PATH)
            if getattr(reg_model, "feature_names_", None):
                reg_features = list(reg_model.feature_names_)

            log.info("PdM models loaded — clf: %d features, reg: %d features",
                     len(clf_features or []), len(reg_features or []))
        except Exception as exc:
            log.warning("Local PdM model loading failed (non-fatal): %s", exc)


def _run_scheduled_batch() -> None:
    """Scheduled job — runs the full PDM batch in a fresh DB session."""
    from app.db.session import SessionLocal
    from app.ai.services.batch_prediction_service import run_batch_for_all_assets

    _load_pdm_models()

    db = SessionLocal()
    try:
        run_batch_for_all_assets(
            db=db,
            clf_model=clf_model,
            clf_features=clf_features,
            clf_threshold=clf_threshold,
            clf_categorical_cols=clf_categorical_cols,
            reg_model=reg_model,
            reg_features=reg_features,
        )
    except Exception:
        log.exception("Batch prediction run failed")
    finally:
        db.close()


def _run_startup_batch() -> None:
    """Startup-only wrapper: waits 10s for Uvicorn to fully bind before running."""
    import time
    time.sleep(10)
    _run_scheduled_batch()


def _ping_hf_models() -> None:
    """Scheduled job — pings HuggingFace models to prevent cold starts."""
    if os.getenv("DISABLE_HF_MODELS", "false").lower() == "true":
        return

    from app.ai.services._hf_inference import call_hf_inference

    repos = [
        "Dinusha-Ekanayake/predictix-asset_summarization_model",
        "Dinusha-Ekanayake/predictix-ticket_summarization_model",
        "Dinusha-Ekanayake/predictix-ticket_categorization_model",
        "Dinusha-Ekanayake/predictix-ticket_prioritization_model",
    ]

    for repo in repos:
        try:
            call_hf_inference(repo, "keep_warm_ping", timeout=30, max_cold_start_wait=20)
            log.debug("Pinged %s to keep warm.", repo)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load PdM models on startup; start batch scheduler; optionally warm HF models."""
    global scheduler

    _load_pdm_models()

    if os.getenv("DISABLE_HF_MODELS", "false").lower() != "true":
        try:
            warmup_ticket_categorizer()
            log.info("Ticket categorization model warmed up.")
        except Exception as exc:
            log.warning("Ticket categorization warmup failed (non-fatal): %s", exc)

        try:
            warmup_ticket_priority()
            log.info("Ticket priority model warmed up.")
        except Exception as exc:
            log.warning("Ticket priority warmup failed (non-fatal): %s", exc)

        try:
            warmup_asset_summary_model()
            log.info("Asset summary model warmed up.")
        except Exception as exc:
            log.warning("Asset summary warmup failed (non-fatal): %s", exc)
    else:
        log.info("HuggingFace models disabled (DISABLE_HF_MODELS=true). Skipping warmup.")

    # ── Hourly batch PDM scheduler ─────────────────────────────────────────────
    batch_interval_hours = int(os.getenv("BATCH_INTERVAL_HOURS", "1"))
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_scheduled_batch,
        trigger="interval",
        hours=batch_interval_hours,
        id="pdm_batch",
        name="PDM hourly batch prediction",
        replace_existing=True,
    )

    if os.getenv("ENABLE_HF_WARMER", "false").lower() == "true":
        scheduler.add_job(
            _ping_hf_models,
            trigger="interval",
            minutes=7,
            jitter=180,
            id="hf_ping",
            name="HF Models Keep-Warm Ping",
            replace_existing=True,
        )
        log.info("HF Inference Warmer enabled (4-10 min intervals).")

    scheduler.start()
    log.info("PDM batch scheduler started — interval=%dh", batch_interval_hours)

    if os.getenv("BATCH_RUN_ON_STARTUP", "false").lower() == "true":
        import threading
        t = threading.Thread(target=_run_startup_batch, daemon=True, name="pdm_batch_startup")
        t.start()
        log.info("PDM batch startup run queued (fires in 10s)")

    yield

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("PDM batch scheduler stopped.")
    log.info("Shutting down PredictiX API.")


app = FastAPI(title="PredictiX API", version="1.0", lifespan=lifespan)

# ── CORS ──────────────────────────────────────────────────────────────────────
_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://predicti-x-frontend.vercel.app",
    "https://predicti-x-frontend-dinusha-ekanayakes-projects.vercel.app",
]
_env_origins = os.getenv("ALLOWED_ORIGINS", "")
_extra_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
_allowed_origins = list(set(_default_origins + _extra_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Router registration ──────────────────────────────────────────────────────
# Auth, users & profiles
app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(users_router)
app.include_router(user_profile_router)

# Organisation
app.include_router(warehouses_router)
app.include_router(departments_router)

# Assets & maintenance
app.include_router(assets_router)
app.include_router(asset_assignments_router)
app.include_router(asset_status_history_router)
app.include_router(asset_documents_router)
app.include_router(asset_summaries_router)
app.include_router(maintenance_router)
app.include_router(sensor_readings_router)

# Tickets
app.include_router(tickets_router)
app.include_router(ticket_comments_router)
app.include_router(ticket_attachments_router)
app.include_router(ticket_status_history_router)
app.include_router(user_tickets_router)

# Predictions & ML
app.include_router(predictions_router)
app.include_router(vehicle_predictions_router)
app.include_router(batch_predictions_router)
app.include_router(prediction_explanations_router)
app.include_router(model_registry_router)
app.include_router(warehouse_dashboard_router)
app.include_router(survival_predictions_router)
app.include_router(admin_dashboard_router)

# Notifications & reports
app.include_router(notifications_router)
app.include_router(notification_preferences_router)
app.include_router(reports_router)
app.include_router(report_sources_router)

# Chatbot
app.include_router(chatbot_router)

# FAQs
app.include_router(faqs_router)

# Diagnostics
app.include_router(db_debug_router)

# WebSockets
app.include_router(websockets_router)


@app.get("/", tags=["Health"])
def root():
    return {
        "message": "PredictiX API running",
        "models_loaded": all(
            x is not None for x in (clf_model, clf_features, reg_model, reg_features)
        ),
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}
