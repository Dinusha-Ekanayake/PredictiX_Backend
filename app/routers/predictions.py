from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db, get_current_user, require_user, assert_asset_in_scope
from app.models import (
    Asset,
    MaintenanceEvent,
    PredictionRun,
    AssetFailurePrediction,
    AssetCostPrediction,
    TicketPrediction,
    Profile,
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
    BreakdownCostPredictionOut,   # ← NEW: matches predict_breakdown_cost()'s real shape
    TicketPredictionOut,
)
from app.ai.services.prediction_service import (
    run_classification,
    run_regression,
    run_health_score,
    run_full_prediction,
)
from app.ai.models.cost_estimation_model.breakdown_cost_model import predict_breakdown_cost

router = APIRouter(
    prefix="/predictions",
    tags=["Predictions"],
    dependencies=[Depends(require_user)],
)


# ── Shared input builder ──────────────────────────────────────────────────────
def _build_cost_input(asset, last_event) -> dict:
    """
    Build raw_input dict for predict_breakdown_cost() from ORM objects.
    Used by both the live endpoint and batch_prediction_service.
    All fields default safely if the column doesn't exist on the model.
    """
    def g(obj, attr, default=None):
        val = getattr(obj, attr, default)
        if val is None or str(val).strip().lower() in ("none", "nan", ""):
            return default
        return val

    return {
        # Identity
        "vehicle_type"                    : g(asset, "vehicle_type", ""),
        "vehicle_role"                    : g(asset, "vehicle_role", "__missing__"),
        "make_model"                      : g(asset, "make_model", "__missing__"),
        "fuel_type"                       : g(asset, "fuel_type", "__missing__"),
        "transmission"                    : g(asset, "transmission", "__missing__"),
        "manufacture_year"                : g(asset, "manufacture_year", 2015),
        # Usage
        "vehicle_age_years"               : g(asset, "vehicle_age_years", 0),
        "payload_capacity_kg"             : g(asset, "payload_capacity_kg", 0),
        "odometer_km"                     : g(asset, "current_mileage", 0),
        "engine_hours_total"              : g(asset, "engine_hours_total", 0),
        "lifetime_service_count"          : g(asset, "lifetime_service_count", 0),
        "lifetime_breakdown_count"        : g(asset, "lifetime_breakdown_count", 0),
        # Health
        "oil_life_pct"                    : g(asset, "oil_life_pct", 50),
        "brake_health_pct"                : g(asset, "brake_health_pct", 50),
        "tire_health_pct"                 : g(asset, "tire_health_pct", 50),
        "battery_health_pct"              : g(asset, "battery_health_pct", 50),
        "hydraulic_health_pct"            : g(asset, "hydraulic_health_pct", 50),
        "active_fault_code_count"         : g(asset, "active_fault_code_count", 0),
        "sensor_fault_flag"               : g(asset, "sensor_fault_flag", 0),
        # Operational
        "fuel_price_lkr_per_l"            : g(asset, "fuel_price_lkr_per_l", 310.0),
        "downtime_hours_last_90d"         : g(asset, "downtime_hours_last_90d", 0),
        "payload_utilization_pct"         : g(asset, "payload_utilization_pct", 50),
        "engine_hours_since_last_service" : g(asset, "engine_hours_since_last_service", 0),
        "days_since_last_service"         : g(asset, "days_since_last_service", 0),
        "mileage_since_last_service_km"   : g(asset, "mileage_since_last_service_km", 0),
        "avg_payload_kg"                  : g(asset, "avg_payload_kg", 0),
        "overload_events_30d"             : g(asset, "overload_events_30d", 0),
        "distance_last_30d_km"            : g(asset, "distance_last_30d_km", 0),
        "operating_hours_last_30d"        : g(asset, "operating_hours_last_30d", 0),
        "idle_hours_last_30d"             : g(asset, "idle_hours_last_30d", 0),
        "trip_count_30d"                  : g(asset, "trip_count_30d", 0),
        "avg_trip_distance_km"            : g(asset, "avg_trip_distance_km", 0),
        "start_stop_burden_30d"           : g(asset, "start_stop_burden_30d", 0),
        "fuel_rate_lph"                   : g(asset, "fuel_rate_lph", 0),
        "fuel_efficiency_km_per_l"        : g(asset, "fuel_efficiency_km_per_l", 0),
        "engine_temp_avg_c"               : g(asset, "engine_temp_avg_c", 85),
        "coolant_temp_max_c"              : g(asset, "coolant_temp_max_c", 95),
        "vibration_rms_mm_s"              : g(asset, "vibration_rms_mm_s", 2.0),
        "tire_pressure_psi"               : g(asset, "tire_pressure_psi", 72),
        "battery_voltage_v"               : g(asset, "battery_voltage_v", 12.5),
        "ambient_temp_avg_c"              : g(asset, "ambient_temp_avg_c", 30),
        "ambient_humidity_avg_pct"        : g(asset, "ambient_humidity_avg_pct", 75),
        "rainfall_mm_30d"                 : g(asset, "rainfall_mm_30d", 100),
        "route_type"                      : g(asset, "route_type", "__missing__"),
        "cargo_type"                      : g(asset, "cargo_type", "__missing__"),
        "operating_shift"                 : g(asset, "operating_shift", "__missing__"),
        "maintenance_priority"            : g(asset, "maintenance_priority", "Medium"),
        # Last maintenance event
        "last_service_type"               : (g(last_event, "service_type", "oil_service") if last_event else "oil_service"),
        "next_service_type"               : (g(last_event, "next_service_type", None) if last_event else None),
        "major_component_replaced"        : (g(last_event, "major_component_replaced", "none") if last_event else "none"),
        "parts_replaced_last_service"     : (g(last_event, "parts_replaced", "") if last_event else ""),
        "service_provider_type"           : (g(last_event, "service_provider_type", "in_house") if last_event else "in_house"),
    }


def _run_cost_prediction_for_asset(asset_id: str, db: Session, current_user: Profile) -> dict:
    """Shared by GET /cost/{asset_id} and POST /cost/live/{asset_id}.
    Runs the breakdown cost model (currently v5.0) live and returns its native dict shape
    plus asset_id/model_version — the fields BreakdownCostPredictionOut expects.
    """
    from app.main import breakdown_cost_bundle

    if breakdown_cost_bundle is None:
        raise HTTPException(status_code=503, detail="Cost model not loaded")

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

    last_event = (
        db.query(MaintenanceEvent)
        .filter(MaintenanceEvent.asset_id == asset_id)
        .order_by(MaintenanceEvent.performed_at.desc())
        .first()
    )
    raw = _build_cost_input(asset, last_event)
    try:
        result = predict_breakdown_cost(raw, breakdown_cost_bundle, top_k=5)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cost prediction failed: {exc}")

    return {
        **result,
        "asset_id": str(asset_id),
        "model_version": breakdown_cost_bundle.get("version"),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
def prediction_health():
    from app.main import clf_model, clf_features, reg_model, reg_features, breakdown_cost_bundle

    return {
        "status": "ok",
        "models_loaded": all([
            clf_model is not None,
            clf_features is not None,
            reg_model is not None,
            reg_features is not None,
        ]),
        "cost_model_loaded": breakdown_cost_bundle is not None,
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
    return run_classification(payload.model_dump(), clf_model, clf_features)


@router.post("/regression", response_model=RegressionResponse)
def regression(payload: PredictionRequest):
    from app.main import reg_model, reg_features

    if reg_model is None:
        raise HTTPException(status_code=500, detail="Regression model is not loaded")
    return run_regression(payload.model_dump(), reg_model, reg_features)


@router.post("/health-score", response_model=HealthScoreResponse)
def health_score(payload: PredictionRequest):
    return run_health_score(payload.model_dump())


@router.post("/full", response_model=FullPredictionResponse)
def full_prediction(payload: PredictionRequest):
    from app.main import clf_model, clf_features, reg_model, reg_features

    if clf_model is None or reg_model is None:
        raise HTTPException(status_code=500, detail="Models are not loaded")
    return run_full_prediction(
        data=payload.model_dump(),
        clf_model=clf_model, clf_features=clf_features,
        reg_model=reg_model, reg_features=reg_features,
    )


@router.get("/runs", response_model=list[PredictionRunOut])
def list_prediction_runs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return db.query(PredictionRun).order_by(PredictionRun.run_started_at.desc()).offset(offset).limit(limit).all()


@router.get("/runs/{run_id}", response_model=PredictionRunOut)
def get_prediction_run(run_id: str, db: Session = Depends(get_db)):
    row = db.query(PredictionRun).filter(PredictionRun.id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prediction run not found")
    return row


@router.get("/failure/{asset_id}", response_model=AssetFailurePredictionOut)
def get_latest_failure_prediction(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

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


@router.get("/cost/{asset_id}", response_model=BreakdownCostPredictionOut)
def get_latest_cost_prediction(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    Return the breakdown cost prediction (currently v5.0) for an asset — always runs live.

    NOTE: this used to check the AssetCostPrediction DB cache first. That table
    (i) is never written by anything — batch_prediction_service.py upserts
    cost into pdm_batch_predictions, not asset_cost_predictions — and (ii)
    even if it were populated, AssetCostPredictionOut has no fields for
    confidence bounds or SHAP drivers. So the cache branch always fell through
    to the live call anyway, except it was previously validated against the
    wrong response_model and would 500. Since predict_breakdown_cost() is
    ~15ms (see model docs §1), always running live is simpler and correct.
    """
    return _run_cost_prediction_for_asset(asset_id, db, current_user)


@router.get("/cost/run/{run_id}", response_model=AssetCostPredictionOut)
def get_cost_prediction_by_run(run_id: str, db: Session = Depends(get_db)):
    row = db.query(AssetCostPrediction).filter(AssetCostPrediction.run_id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Cost prediction not found")
    return row


@router.post("/cost/live/{asset_id}", response_model=BreakdownCostPredictionOut)
def run_live_cost_prediction(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    Force-run the breakdown cost model for one asset, bypassing cache.
    (Functionally identical to GET /cost/{asset_id} now that that endpoint
    always runs live too — kept as a separate route for API-contract/semantic
    compatibility with existing callers that POST here after a maintenance
    event to refresh the estimate.)
    """
    return _run_cost_prediction_for_asset(asset_id, db, current_user)


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