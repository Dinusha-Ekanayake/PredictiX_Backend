from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import MaintenanceEvent
from app.schemas.maintenance import (
    MaintenanceEventCreate,
    MaintenanceEventUpdate,
    MaintenanceEventOut,
    LogMaintenancePayload,
)
from app.services.in_app_notification_service import InAppNotificationService
from app.models import Asset, SensorReading
from datetime import datetime
import uuid

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.post("/", response_model=MaintenanceEventOut)
def create_maintenance_event(payload: MaintenanceEventCreate, db: Session = Depends(get_db)):
    obj = MaintenanceEvent(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    
    # Notify assigned user
    try:
        asset = db.query(Asset).filter(Asset.id == obj.asset_id).first()
        if asset and asset.assigned_to:
            InAppNotificationService.notify_user(
                db=db,
                user_id=str(asset.assigned_to),
                title="Maintenance Scheduled",
                message=f"Heads up! Asset {asset.asset_code or 'assigned to you'} is scheduled for maintenance: {obj.title}.",
                priority="medium",
                notification_type="general",
                link_url=f"/user/assets/{asset.id}"
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to send maintenance notification: %s", exc)
        
    return obj


@router.get("/", response_model=list[MaintenanceEventOut])
def list_maintenance_events(
    asset_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(MaintenanceEvent)
    if asset_id:
        q = q.filter(MaintenanceEvent.asset_id == asset_id)
    if event_type:
        q = q.filter(MaintenanceEvent.event_type == event_type)
    return q.order_by(MaintenanceEvent.created_at.desc()).all()


@router.get("/{event_id}", response_model=MaintenanceEventOut)
def get_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    return obj


@router.put("/{event_id}", response_model=MaintenanceEventOut)
def update_maintenance_event(event_id: str, payload: MaintenanceEventUpdate, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{event_id}")
def delete_maintenance_event(event_id: str, db: Session = Depends(get_db)):
    obj = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == event_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    db.delete(obj)
    db.commit()
    return {"message": "Maintenance event deleted"}


@router.post("/log-maintenance/{asset_id}", response_model=MaintenanceEventOut)
def log_maintenance_and_predict(asset_id: str, payload: LogMaintenancePayload, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    performed_at = payload.performed_at or datetime.utcnow()
    if performed_at > datetime.utcnow():
        raise HTTPException(status_code=400, detail="performed_at cannot be in the future")

    if payload.next_service_date and payload.next_service_date <= performed_at:
        raise HTTPException(status_code=400, detail="Next service date must be after performed date")

    if payload.cost_amount < 0:
        raise HTTPException(status_code=400, detail="Cost cannot be negative")

    if asset.current_mileage and payload.odometer_reading < asset.current_mileage:
        raise HTTPException(status_code=400, detail="Odometer reading cannot be less than current mileage")

    # 1. Update Asset
    asset.last_service_date = performed_at
    if payload.next_service_date:
        asset.next_service_date = payload.next_service_date
    asset.status = "active"
    asset.current_mileage = payload.odometer_reading
    db.add(asset)

    # 2. Create Maintenance Event
    m_event = MaintenanceEvent(
        id=uuid.uuid4(),
        asset_id=asset.id,
        event_type="corrective",
        title=payload.title,
        description=payload.description,
        performed_at=performed_at,
        scheduled_date=payload.next_service_date,
        cost_amount=payload.cost_amount,
        odometer_reading=payload.odometer_reading,
        notes=payload.notes,
        currency="LKR",
    )
    db.add(m_event)

    # 3. Create "Healthy" Sensor Reading
    last_reading = db.query(SensorReading).filter(SensorReading.asset_id == asset_id).order_by(SensorReading.recorded_at.desc()).first()
    
    new_reading = SensorReading(
        id=uuid.uuid4(),
        asset_id=asset.id,
        recorded_at=datetime.utcnow(),
        # Reset health metrics to 100%
        tire_health_pct=100.0,
        brake_health_pct=100.0,
        battery_health_pct=100.0,
        oil_life_pct=100.0,
        hydraulic_health_pct=100.0,
        # Reset counters
        engine_hours_since_last_service=0.0,
        days_since_last_service=0,
        mileage_since_last_service_km=0.0,
        active_fault_code_count=0,
        downtime_hours_last_90d=0.0,
        vibration_rms_mm_s=0.1,
        # Copy ambient/static metrics from last reading if available
        engine_hours_total=last_reading.engine_hours_total if last_reading else 0.0,
        coolant_temp_max_c=last_reading.coolant_temp_max_c if last_reading else 85.0,
        engine_temp_avg_c=last_reading.engine_temp_avg_c if last_reading else 85.0,
        battery_voltage_v=last_reading.battery_voltage_v if last_reading else 12.6,
        ambient_humidity_avg_pct=last_reading.ambient_humidity_avg_pct if last_reading else 50.0,
        fuel_price_lkr_per_l=last_reading.fuel_price_lkr_per_l if last_reading else 350.0,
        odometer_km=payload.odometer_reading,
    )
    db.add(new_reading)
    db.commit()
    db.refresh(m_event)

    # 4. Trigger AI Prediction
    from app.main import _load_pdm_models, clf_model, clf_features, reg_model, reg_features
    _load_pdm_models()
    
    if clf_model is not None and reg_model is not None:
        from app.ai.services.vehicle_prediction_service import run_vehicle_prediction_and_store
        try:
            run_vehicle_prediction_and_store(
                db=db,
                asset_id=str(asset.id),
                requested_by=None,
                clf_model=clf_model,
                clf_features=clf_features,
                reg_model=reg_model,
                reg_features=reg_features,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to run prediction post-maintenance: %s", e)

    return m_event