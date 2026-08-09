from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps import get_db, get_current_user, require_admin, require_user, assert_asset_in_scope
from app.models import SensorReading, Asset, Profile
from app.schemas.sensor import SensorReadingCreate, SensorReadingOut

router = APIRouter(
    prefix="/sensor-readings",
    tags=["Sensor Readings"],
    dependencies=[Depends(require_user)],
)

@router.post("/", dependencies=[Depends(require_admin)])
def create_sensor_reading(
    payload: SensorReadingCreate,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == payload.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

    obj = SensorReading(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"message": "Sensor reading created", "id": obj.id}

@router.get("/asset/{asset_id}", response_model=list[SensorReadingOut])
def get_asset_sensor_readings(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    assert_asset_in_scope(asset, current_user)

    rows = (
        db.query(SensorReading)
        .filter(SensorReading.asset_id == asset_id)
        .order_by(SensorReading.recorded_at.desc())
        .limit(50)
        .all()
    )
    return rows