from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from uuid import UUID
from typing import Dict, Any
from datetime import datetime, timedelta
from app.models import (
    Asset,
    Warehouse,
    AssetFailurePrediction,
    AssetCostPrediction,
    MaintenanceEvent,
    Profile,
    Ticket,
    SensorReading
)

class AssetReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_asset_context(self, asset_id: UUID) -> Dict[str, Any]:
        """Fetches all necessary data to build the asset report."""
        
        # 1. Fetch Asset & Warehouse
        asset_stmt = select(Asset).where(Asset.id == asset_id)
        asset = self.db.execute(asset_stmt).scalar_one_or_none()
        
        if not asset:
            return None

        warehouse = self.db.execute(select(Warehouse).where(Warehouse.id == asset.warehouse_id)).scalar_one_or_none()
        
        assigned_person = None
        if asset.assigned_to:
            assigned_person = self.db.execute(select(Profile).where(Profile.id == asset.assigned_to)).scalar_one_or_none()

        # 2. Fetch Latest Predictions
        failure_pred_stmt = select(AssetFailurePrediction).where(
            AssetFailurePrediction.asset_id == asset_id
        ).order_by(desc(AssetFailurePrediction.created_at)).limit(1)
        failure_pred = self.db.execute(failure_pred_stmt).scalar_one_or_none()

        cost_pred_stmt = select(AssetCostPrediction).where(
            AssetCostPrediction.asset_id == asset_id
        ).order_by(desc(AssetCostPrediction.created_at)).limit(1)
        cost_pred = self.db.execute(cost_pred_stmt).scalar_one_or_none()

        # 3. Fetch Maintenance History
        maintenance_stmt = select(MaintenanceEvent).where(
            MaintenanceEvent.asset_id == asset_id
        ).order_by(desc(MaintenanceEvent.scheduled_date)).limit(5)
        maintenance_events = self.db.execute(maintenance_stmt).scalars().all()



        return {
            "asset": asset,
            "warehouse": warehouse,
            "assigned_person": assigned_person,
            "failure_prediction": failure_pred,
            "cost_prediction": cost_pred,
            "maintenance_events": maintenance_events
        }
