from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models import SensorReading, Asset
from app.schemas.sensor import SensorReadingCreate

router = APIRouter(prefix="/sensor-readings", tags=["Sensor Readings"])

@router.post("/")
def create_sensor_reading(payload: SensorReadingCreate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    obj = SensorReading(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"message": "Sensor reading created", "id": obj.id}

@router.get("/asset/{asset_id}")
def get_asset_sensor_readings(asset_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(SensorReading)
        .filter(SensorReading.asset_id == asset_id)
        .order_by(SensorReading.recorded_at.desc())
        .limit(50)
        .all()
    )
    return rows