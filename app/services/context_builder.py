"""
app/services/context_builder.py

Queries all data needed for the Asset Performance Report from the DB
using the exact SQLAlchemy model fields defined in app/models.py.

Models used:
    Asset, MaintenanceEvent, Ticket,
    AssetFailurePrediction, AssetCostPrediction,
    SensorReading, Warehouse, Department
"""

from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session, defer
from fastapi import HTTPException

from app.models import (
    Asset,
    MaintenanceEvent,
    Ticket,
    AssetFailurePrediction,
    AssetCostPrediction,
    SensorReading,
    Warehouse,
    Department,
)


def _str(val, default="—") -> str:
    """Safely convert any value to string, returning default for None."""
    if val is None:
        return default
    return str(val)


def _float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _date(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _datetime(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)


class AssetContextBuilder:
    """
    Builds the full context dict consumed by PDFRenderService.generate_pdf().
    One instance per request — holds a DB session.
    """

    def __init__(self, db: Session):
        self.db = db

    def build_context(self, asset_id: UUID) -> dict:
        """
        Main entry point. Runs all queries and returns a single context dict.
        Raises HTTPException(404) if the asset does not exist.
        """
        # ── 1. Asset ──────────────────────────────────────
        asset: Asset = (
            self.db.query(Asset)
            .filter(Asset.id == asset_id)
            .first()
        )
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

        # ── 2. Warehouse & Department (for display names) ──
        warehouse = None
        department = None
        if asset.warehouse_id:
            warehouse = self.db.query(Warehouse).filter(Warehouse.id == asset.warehouse_id).first()
        if asset.department_id:
            department = self.db.query(Department).filter(Department.id == asset.department_id).first()

        # ── 3. Maintenance events (newest first) ───────────
        maintenance = (
            self.db.query(MaintenanceEvent)
            .options(defer(MaintenanceEvent.meta))
            .filter(MaintenanceEvent.asset_id == asset_id)
            .order_by(MaintenanceEvent.performed_at.desc().nulls_last(),
                      MaintenanceEvent.created_at.desc())
            .all()
        )

        # ── 4. Tickets (newest first) ──────────────────────
        tickets = (
            self.db.query(Ticket)
            .options(defer(Ticket.meta))
            .filter(Ticket.asset_id == asset_id)
            .order_by(Ticket.created_at.desc())
            .all()
        )

        # ── 5. Latest failure prediction ───────────────────
        failure_pred: AssetFailurePrediction = (
            self.db.query(AssetFailurePrediction)
            .filter(AssetFailurePrediction.asset_id == asset_id)
            .order_by(AssetFailurePrediction.created_at.desc())
            .first()
        )

        # ── 6. Latest cost prediction ──────────────────────
        cost_pred: AssetCostPrediction = (
            self.db.query(AssetCostPrediction)
            .filter(AssetCostPrediction.asset_id == asset_id)
            .order_by(AssetCostPrediction.created_at.desc())
            .first()
        )

        # ── 7. Latest sensor reading ───────────────────────
        sensor: SensorReading = (
            self.db.query(SensorReading)
            .filter(SensorReading.asset_id == asset_id)
            .order_by(SensorReading.recorded_at.desc())
            .first()
        )

        # ── 8. Aggregate maintenance metrics ──────────────
        total_events  = len(maintenance)
        preventive    = sum(1 for m in maintenance if (m.event_type or "").lower() == "preventive")
        corrective    = total_events - preventive
        total_cost    = sum(_float(m.cost_amount) for m in maintenance)
        total_downtime = sum(_float(m.downtime_hours) for m in maintenance)

        # ── 9. Ticket metrics ─────────────────────────────
        open_tickets      = [t for t in tickets if (t.status or "").lower() in ("open", "in_progress")]
        high_priority     = [t for t in open_tickets if (t.priority or "").lower() == "high"]
        closed_tickets    = [t for t in tickets if (t.status or "").lower() in ("closed", "resolved")]

        # ── 10. AI prediction metrics ─────────────────────
        health_score     = _float(getattr(failure_pred, "health_score",     None)) if failure_pred else 100.0
        failure_prob     = _float(getattr(failure_pred, "failure_probability", None)) * 100 if failure_pred else 0.0
        risk_level       = getattr(failure_pred, "risk_level", None) or _band_risk(health_score)
        days_until_maint = getattr(failure_pred, "days_until_maintenance", None)
        pred_maint_date  = _date(getattr(failure_pred, "predicted_maintenance_date", None))
        top_explanations = getattr(failure_pred, "top_explanations", {}) or {}

        est_cost   = _float(getattr(cost_pred, "estimated_cost", None)) if cost_pred else 0.0
        min_cost   = _float(getattr(cost_pred, "min_cost",       None)) if cost_pred else 0.0
        max_cost   = _float(getattr(cost_pred, "max_cost",       None)) if cost_pred else 0.0
        currency   = getattr(cost_pred, "currency", "LKR") if cost_pred else "LKR"

        return {
            "generated_date": datetime.now().strftime("%B %d, %Y"),
            "report_id":      str(asset_id)[:8].upper(),

            # ── Asset core info ──────────────────────────
            "asset": {
                "id":                  _str(asset.id),
                "asset_code":          _str(asset.asset_code),
                "asset_name":          _str(asset.asset_name),
                "asset_type":          _str(asset.asset_type),
                "vehicle_type":        _str(asset.vehicle_type),
                "make":                _str(asset.make),
                "model":               _str(asset.model),
                "manufacture_year":    _str(asset.manufacture_year),
                "registration_number": _str(asset.registration_number),
                "vin":                 _str(asset.vin),
                "status":              _str(asset.status),
                "health_band":         _str(asset.health_band),
                "criticality_score":   _str(asset.criticality_score),
                "purchase_date":       _date(asset.purchase_date),
                "warranty_expiry_date":_date(asset.warranty_expiry_date),
                "last_service_date":   _date(asset.last_service_date),
                "next_service_date":   _date(asset.next_service_date),
                "current_mileage":     _str(asset.current_mileage),
                "vehicle_age_years":   _str(asset.vehicle_age_years),
                "payload_capacity_kg": _str(asset.payload_capacity_kg),
                "vehicle_role":        _str(asset.vehicle_role),
                "lifetime_service_count":   _str(asset.lifetime_service_count),
                "lifetime_breakdown_count": _str(asset.lifetime_breakdown_count),
                "description":         _str(asset.description),
                "warehouse":           _str(getattr(warehouse,  "name", None)),
                "department":          _str(getattr(department, "name", None)),
            },

            # ── Raw ORM rows (for table rendering) ──────
            "maintenance":  maintenance,
            "tickets":      tickets,

            # ── Sensor snapshot ──────────────────────────
            "sensor": {
                "recorded_at":                   _datetime(getattr(sensor, "recorded_at",  None)),
                "tire_health_pct":               _str(getattr(sensor, "tire_health_pct",   None)),
                "brake_health_pct":              _str(getattr(sensor, "brake_health_pct",  None)),
                "battery_health_pct":            _str(getattr(sensor, "battery_health_pct",None)),
                "oil_life_pct":                  _str(getattr(sensor, "oil_life_pct",      None)),
                "hydraulic_health_pct":          _str(getattr(sensor, "hydraulic_health_pct",None)),
                "coolant_temp_max_c":            _str(getattr(sensor, "coolant_temp_max_c",None)),
                "engine_temp_avg_c":             _str(getattr(sensor, "engine_temp_avg_c", None)),
                "active_fault_code_count":       _str(getattr(sensor, "active_fault_code_count",None)),
                "days_since_last_service":       _str(getattr(sensor, "days_since_last_service", None)),
                "engine_hours_since_last_service":_str(getattr(sensor,"engine_hours_since_last_service",None)),
                "downtime_hours_last_90d":       _str(getattr(sensor, "downtime_hours_last_90d", None)),
                "fuel_level":                    _str(getattr(sensor, "fuel_level",        None)),
                "odometer_km":                   _str(getattr(sensor, "odometer_km",       None)),
            } if sensor else {},

            # ── Pre-computed metrics ─────────────────────
            "metrics": {
                "total_events":            total_events,
                "preventive_count":        preventive,
                "corrective_count":        corrective,
                "preventive_ratio":        round(preventive / total_events * 100, 1) if total_events else 0,
                "corrective_ratio":        round(corrective / total_events * 100, 1) if total_events else 0,
                "total_cost":              total_cost,
                "avg_cost_per_event":      round(total_cost / total_events, 2) if total_events else 0,
                "total_downtime_hours":    round(total_downtime, 1),
                "total_tickets":           len(tickets),
                "open_tickets":            len(open_tickets),
                "high_priority_tickets":   len(high_priority),
                "closed_tickets":          len(closed_tickets),
                "health_score":            round(health_score, 1),
                "failure_probability":     round(failure_prob, 1),
                "risk_level":              risk_level,
                "days_until_maintenance":  days_until_maint,
                "predicted_maintenance_date": pred_maint_date,
                "estimated_cost":          est_cost,
                "min_cost":                min_cost,
                "max_cost":                max_cost,
                "currency":                currency,
                "top_explanations":        top_explanations,
            },
        }


def _band_risk(health_score: float) -> str:
    """Derive risk level from health score when no prediction row exists."""
    if health_score < 60:
        return "Critical"
    if health_score < 75:
        return "High"
    if health_score < 90:
        return "Medium"
    return "Low"