"""PredictiX API — FastAPI application entry point."""
from __future__ import annotations

import os

# Force HuggingFace libraries offline BEFORE any of them can be imported, so no
# model weights are ever downloaded/loaded from the Hub at runtime. Only the
# online Gradio Space (plain HTTP) and the local PdM/cost/survival .pkl models
# (loaded via joblib/pickle, not the Hub) are used. These are hard defaults;
# they can still be overridden by an explicit environment value if ever needed.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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
from .routers.ticket_summaries import router as ticket_summaries_router
from .routers.asset_component_rul import router as asset_component_rul_router
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
from .routers.asset_reports import router as asset_reports_router, reports_router
from .routers.warmup import router as warmup_router

# Sharada — user-role self-service profile (/user-profile)
from .routers.user_profile import router as user_profile_router
# Sharada — user-role ticket section (/user/tickets)
from .routers.user_tickets import router as user_tickets_router
# Sharada — FRSO warehouse-level survival predictions (/survival/*)
from .routers.survival_predictions import router as survival_predictions_router

# ─── ML warmup ────────────────────────────────────────────────────────────────
# Asset & ticket summaries run on HF Spaces (online) — nothing to warm up here.
from app.ai.services.ticket_categorization_service import warmup_ticket_categorizer
from app.ai.services.ticket_priority_service import warmup_ticket_priority

# ─── Cost model ───────────────────────────────────────────────────────────────
from app.ai.models.cost_estimation_model.breakdown_cost_model import load_breakdown_bundle

log = logging.getLogger("predictix")

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "ai" / "models"

# v7 LightGBM boosters (current). Old v5/v6 CatBoost/XGBoost bundles are kept
# on disk under each model folder's old/ subdirectory as an archive — not
# loaded anywhere in the app.
CLF_MODEL_PATH = MODEL_DIR / "pdm_classifier_model" / "predictix_pdm_classifier_v7.txt"
REG_MODEL_PATH = MODEL_DIR / "pdm_regressor_model"  / "predictix_pdm_regressor_v7.txt"
CLF_DECISION_LOG_PATH = MODEL_DIR / "pdm_classifier_model" / "classifier_v7_decision_log.json"
REG_DECISION_LOG_PATH = MODEL_DIR / "pdm_regressor_model"  / "regressor_v7_decision_log.json"

# Same names used as the model_registry.model_name keys throughout the app —
# kept in sync with app.ai.services.vehicle_prediction_service.
CLASSIFIER_MODEL_NAME = "pdm_classifier_model"
REGRESSOR_MODEL_NAME = "pdm_regressor_model"

clf_model = None            # LgbModelBundle
clf_features: list = []
clf_threshold: float = 0.5
clf_categorical_cols: list = []
reg_model = None            # LgbModelBundle
reg_features: list = []
reg_categorical_cols: list = []

# ─── Cost model global ────────────────────────────────────────────────────────
breakdown_cost_bundle: dict | None = None

scheduler: BackgroundScheduler | None = None
_model_load_lock = __import__('threading').Lock()


def _load_decision_log(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _upsert_model_registry(db, model_name: str, model_type: str, version: str, artifact_path: Path, metrics: dict) -> None:
    from app.models import ModelRegistry

    existing = (
        db.query(ModelRegistry)
        .filter(ModelRegistry.model_name == model_name, ModelRegistry.version == version)
        .first()
    )
    if existing:
        existing.framework = "lightgbm"
        existing.artifact_path = str(artifact_path)
        existing.metrics = metrics
        existing.is_active = True
    else:
        db.add(ModelRegistry(
            model_name=model_name,
            model_type=model_type,
            version=version,
            framework="lightgbm",
            artifact_path=str(artifact_path),
            metrics=metrics,
            is_active=True,
        ))
    # Deactivate any other version of this model so is_active always points
    # at exactly the model generation currently loaded in memory.
    db.query(ModelRegistry).filter(
        ModelRegistry.model_name == model_name, ModelRegistry.version != version
    ).update({"is_active": False})


def _register_active_models() -> None:
    from app.db.session import SessionLocal

    clf_log = _load_decision_log(CLF_DECISION_LOG_PATH)
    reg_log = _load_decision_log(REG_DECISION_LOG_PATH)

    db = SessionLocal()
    try:
        if clf_log:
            _upsert_model_registry(
                db, CLASSIFIER_MODEL_NAME, "failure_classification",
                str(clf_log.get("version", "unknown")), CLF_MODEL_PATH, clf_log,
            )
        if reg_log:
            _upsert_model_registry(
                db, REGRESSOR_MODEL_NAME, "maintenance_regression",
                str(reg_log.get("version", "unknown")), REG_MODEL_PATH, reg_log,
            )
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to register active PdM models in model_registry")
    finally:
        db.close()


def _load_pdm_models():
    """Lazily load heavy PdM models (thread-safe, idempotent)."""
    global clf_model, clf_features, clf_threshold, clf_categorical_cols, \
           reg_model, reg_features, reg_categorical_cols
    if clf_model is not None and reg_model is not None:
        return

    with _model_load_lock:
        if clf_model is not None and reg_model is not None:
            return
        try:
            from app.ai.services.lgb_model_adapter import LgbModelBundle

            clf_model = LgbModelBundle(CLF_MODEL_PATH)
            clf_features = clf_model.feature_names
            clf_categorical_cols = clf_model.categorical_cols

            reg_model = LgbModelBundle(REG_MODEL_PATH)
            reg_features = reg_model.feature_names
            reg_categorical_cols = reg_model.categorical_cols

            clf_log = _load_decision_log(CLF_DECISION_LOG_PATH)
            clf_threshold = float(clf_log.get("threshold_max_f1", 0.5))

            log.info(
                "PdM v7 LightGBM models loaded — clf: %d features (threshold=%.3f), reg: %d features",
                len(clf_features), clf_threshold, len(reg_features),
            )

            try:
                _register_active_models()
            except Exception:
                log.exception("model_registry upsert failed (non-fatal)")
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
            reg_categorical_cols=reg_categorical_cols,
            cost_bundle=breakdown_cost_bundle,
        )
    except Exception:
        log.exception("Batch prediction run failed")
    finally:
        db.close()


def _run_service_reminder_job() -> None:
    """Scheduled job — daily sweep for assets due within reminder windows."""
    from app.db import SessionLocal
    from app.services.service_reminder_service import run_auto_reminder_sweep

    db = SessionLocal()
    try:
        run_auto_reminder_sweep(db)
    except Exception:
        log.exception("Service reminder sweep failed")
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
    global scheduler, cost_bundle

    _load_pdm_models()

    # ─── Breakdown cost estimation model (v5 — CatBoost) ─────────────────────
    global breakdown_cost_bundle
    try:
        breakdown_cost_bundle = load_breakdown_bundle()
        log.info("Breakdown cost model bundle loaded successfully.")
    except Exception as exc:
        log.error(
            "Breakdown cost model loading FAILED — /predictions/cost/* will "
            "503 until this is fixed: %s", exc, exc_info=True,
        )

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

        # Asset & ticket summaries run online on HF Spaces — no local warmup.
    else:
        log.info("HuggingFace models disabled (DISABLE_HF_MODELS=true). Skipping warmup.")

    # ── Batch PDM scheduler ─────────────────────────────────────────────────────
    batch_interval_hours = int(os.getenv("BATCH_INTERVAL_HOURS", "24"))
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_scheduled_batch,
        trigger="interval",
        hours=batch_interval_hours,
        id="pdm_batch",
        name=f"PDM batch prediction (every {batch_interval_hours}h)",
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

    # ── Daily service reminder email sweep ─────────────────────────────────────
    reminder_hour = int(os.getenv("SERVICE_REMINDER_HOUR", "9"))
    reminder_tz = os.getenv("SERVICE_REMINDER_TZ", "Asia/Colombo")
    scheduler.add_job(
        _run_service_reminder_job,
        trigger=CronTrigger(hour=reminder_hour, minute=0, timezone=reminder_tz),
        id="service_reminder_check",
        name="Daily service reminder email sweep",
        replace_existing=True,
    )
    log.info(
        "Service reminder scheduler registered — daily at %d:00 %s",
        reminder_hour, reminder_tz,
    )

    if os.getenv("SERVICE_REMINDER_RUN_ON_STARTUP", "false").lower() == "true":
        import threading
        threading.Thread(
            target=_run_service_reminder_job,
            daemon=True,
            name="service_reminder_startup",
        ).start()
        log.info("Service reminder startup run queued")

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
_prod_origins = [
    "https://predicti-x-frontend.vercel.app",
    "https://predicti-x-frontend-dinusha-ekanayakes-projects.vercel.app",
]
_dev_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.56.1:3000",
    "http://192.168.56.1:3001",
]

_is_production = os.getenv("ENV", "").strip().lower() == "production"
_env_origins = os.getenv("ALLOWED_ORIGINS", "")
_extra_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]

_allowed_origins = list(set(_prod_origins + _extra_origins))
if not _is_production:
    _allowed_origins = list(set(_allowed_origins + _dev_origins))

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
app.include_router(ticket_summaries_router)
app.include_router(asset_component_rul_router)

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
app.include_router(asset_reports_router)

# Chatbot
app.include_router(chatbot_router)

# FAQs
app.include_router(faqs_router)

# Diagnostics
if os.getenv("ENABLE_DEBUG_ROUTES", "false").strip().lower() == "true":
    app.include_router(db_debug_router)
    log.info("Debug routes enabled (ENABLE_DEBUG_ROUTES=true).")

# WebSockets
app.include_router(websockets_router)

# Public warmup ping
app.include_router(warmup_router)


@app.get("/", tags=["Health"])
def root():
    return {
        "message": "PredictiX API running",
        "models_loaded": all(
            x is not None for x in (clf_model, clf_features, reg_model, reg_features)
        ),
        "cost_model_loaded": breakdown_cost_bundle is not None,
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return {}