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

# v6 XGBoost classifier — saved as a bundle dict {model, feature_cols, threshold, categorical_cols, ...}
CLF_BUNDLE_PATH = MODEL_DIR / "pdm_classifier_model" / "predictix_xgboost_classifier_v6.pkl"
# v5 regressor — saved via joblib as a bundle dict {explainer_model, feature_cols, ...}
REG_BUNDLE_PATH = MODEL_DIR / "pdm_regressor_model" / "predictix_pm_model_v5.pkl"

clf_model = None
clf_features: list = []
clf_threshold: float = 0.5
clf_categorical_cols: list = []
reg_model = None
reg_features: list = []


def _load_pickle(path: Path):
    with open(path, "rb") as fh:
        return pickle.load(fh)


scheduler: BackgroundScheduler | None = None
_model_load_lock = __import__('threading').Lock()

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
    """Startup-only wrapper: waits for Uvicorn to fully bind before running the batch."""
    import time
    time.sleep(10)  # Give the server 10s to stabilise before loading 100MB models
    _run_scheduled_batch()


def _ping_hf_models() -> None:
    """Scheduled job — constantly pings Hugging Face models to prevent cold starts."""
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
            # Minimal payload to wake the model up. It may return an error, but the 
            # HTTP request successfully forces HF to keep the container alive in VRAM.
            call_hf_inference(repo, "keep_warm_ping", timeout=30, max_cold_start_wait=20)
            log.debug("Pinged %s to keep warm.", repo)
        except Exception as e:
            # Ignore expected inference errors (like ValueError for bad shape),
            # the request still hit the router and woke the model up.
            pass


def _load_pdm_models():
    """Lazily load heavy PdM models (thread-safe, idempotent)."""
    global clf_model, clf_features, clf_threshold, clf_categorical_cols, reg_model, reg_features
    if clf_model is not None and reg_model is not None:
        return

    with _model_load_lock:
        # Double-check inside the lock (another thread may have loaded while we waited)
        if clf_model is not None and reg_model is not None:
            return
        try:
            with open(CLF_BUNDLE_PATH, "rb") as fh:
                clf_bundle = pickle.load(fh)
            clf_model            = clf_bundle["model"]
            clf_features         = clf_bundle["feature_cols"]
            clf_threshold        = float(clf_bundle.get("threshold", 0.5))
            clf_categorical_cols = clf_bundle.get("categorical_cols", [])

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                reg_bundle = joblib.load(REG_BUNDLE_PATH)
            reg_model    = reg_bundle["explainer_model"]
            reg_features = reg_bundle["feature_cols"]
            if getattr(reg_model, "feature_names_", None):
                reg_features = list(reg_model.feature_names_)

            log.info(
                "PdM models loaded — clf v6-XGB: %d features (threshold=%.2f), reg v5: %d features",
                len(clf_features), clf_threshold, len(reg_features),
            )
        except Exception as exc:
            log.exception("Local PdM model loading failed")
            raise RuntimeError(f"Failed to load local PdM models: {exc}") from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start hourly batch scheduler; optionally warm HF models."""
    global scheduler

    if os.getenv("DISABLE_HF_MODELS", "false").lower() != "true":
        try:
            warmup_ticket_categorizer()
            log.info("Ticket categorization model warmed up.")
        except Exception as exc:
            log.exception("Ticket categorization warmup failed")
            raise RuntimeError(f"Failed to load ticket categorization model: {exc}") from exc

        try:
            warmup_asset_summary_model()
            log.info("Asset summary model warmed up.")
        except Exception as exc:
            log.exception("Asset summary warmup failed")
            raise RuntimeError(f"Failed to load asset summary model: {exc}") from exc
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
    
    # ── Keep-Warm ping for HF Models ───────────────────────────────────────────
    if os.getenv("ENABLE_HF_WARMER", "false").lower() == "true":
        scheduler.add_job(
            _ping_hf_models,
            trigger="interval",
            minutes=7,       # Base interval: 7 minutes
            jitter=180,      # Add/subtract up to 3 minutes randomly (4 to 10 minute range)
            id="hf_ping",
            name="HF Models Keep-Warm Ping",
            replace_existing=True,
        )
        log.info("HF Inference Warmer enabled with dynamic intervals (4-10 mins).")
    
    scheduler.start()
    log.info("PDM batch scheduler started — interval=%dh", batch_interval_hours)

    # Optionally trigger a batch run on startup (runs 10s AFTER server is stable)
    if os.getenv("BATCH_RUN_ON_STARTUP", "false").lower() == "true":
        import threading
        t = threading.Thread(target=_run_startup_batch, daemon=True, name="pdm_batch_startup")
        t.start()
        log.info("PDM batch startup run queued (fires in 10s)")

    # Signal Uvicorn to bind port and start serving traffic
    yield

    # ── Graceful shutdown ──────────────────────────────────────────────────────
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("PDM batch scheduler stopped.")
    log.info("Shutting down PredictiX API.")


app = FastAPI(title="PredictiX API", version="1.0", lifespan=lifespan)

# ── CORS ──────────────────────────────────────────────────────────────────────
# ALLOWED_ORIGINS env var: comma-separated list of allowed origins.
# Set this in Railway dashboard to your frontend URL(s).
# Example: https://predictix.vercel.app,https://predictix.netlify.app
_default_origins = [
    # Local development
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Vercel production + preview deployments
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
app.include_router(user_profile_router)        # Sharada — user-role profile

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
app.include_router(user_tickets_router)        # Sharada — user-role ticket section

# Predictions & ML
app.include_router(predictions_router)
app.include_router(vehicle_predictions_router)
app.include_router(batch_predictions_router)       # hourly cached predictions
app.include_router(prediction_explanations_router)
app.include_router(model_registry_router)
app.include_router(warehouse_dashboard_router)
app.include_router(survival_predictions_router)  # Sharada — FRSO survival predictions
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
