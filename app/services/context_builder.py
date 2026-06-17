"""
app/services/context_builder.py

Queries all data needed for the Asset Performance Report from Supabase
using the Supabase Python REST client (no direct DB connection required).
RLS-blocked tables are handled gracefully and return None / empty list.
"""

from uuid import UUID
from datetime import datetime
from fastapi import HTTPException
from supabase import create_client, Client
import os
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)


def _str(val, default="—") -> str:
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
    if isinstance(val, str):
        return val[:10]
    return str(val)


def _datetime(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")
    if isinstance(val, str):
        return val[:16].replace("T", " ")
    return str(val)


def _get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_KEY not set in .env")
    return create_client(url, key)


def _fetch_admin_summary() -> dict:
    """Fetch fleet-level summary from the admin dashboard API."""
    try:
        base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
        resp = httpx.get(f"{base}/admin-dashboard/summary", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[context_builder] WARNING: Could not fetch admin summary: {e}")
    return {}


class AssetContextBuilder:
    def __init__(self, db=None):
        self.supabase: Client = _get_supabase()

    def _fetch_one(self, table: str, filters: dict, columns: str = "*") -> dict | None:
        try:
            query = self.supabase.table(table).select(columns)
            for col, val in filters.items():
                query = query.eq(col, str(val))
            result = query.limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"[context_builder] WARNING: Could not fetch from '{table}': {e}")
            return None

    def _fetch_many(self, table: str, filters: dict, order_col: str = None,
                    order_desc: bool = True, columns: str = "*") -> list:
        try:
            query = self.supabase.table(table).select(columns)
            for col, val in filters.items():
                query = query.eq(col, str(val))
            if order_col:
                query = query.order(order_col, desc=order_desc)
            result = query.execute()
            return result.data or []
        except Exception as e:
            print(f"[context_builder] WARNING: Could not fetch from '{table}': {e}")
            return []

    def _fetch_status_distribution(self) -> list:
        """Get asset count by status."""
        try:
            result = self.supabase.table("assets").select("status").execute()
            counts = {}
            for row in (result.data or []):
                s = (row.get("status") or "unknown").lower()
                counts[s] = counts.get(s, 0) + 1
            return [{"name": k.title(), "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
        except Exception as e:
            print(f"[context_builder] WARNING: Could not fetch status distribution: {e}")
            return []

    def _fetch_vehicle_type_distribution(self) -> list:
        """Get asset count by vehicle_type."""
        try:
            result = self.supabase.table("assets").select("vehicle_type").execute()
            counts = {}
            for row in (result.data or []):
                vt = row.get("vehicle_type") or "Unknown"
                counts[vt] = counts.get(vt, 0) + 1
            return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])[:10]]
        except Exception as e:
            print(f"[context_builder] WARNING: Could not fetch vehicle type distribution: {e}")
            return []

    def build_context(self, asset_id: UUID) -> dict:
        asset_id_str = str(asset_id)

        # ── 1. Asset ──────────────────────────────────────
        asset = self._fetch_one("assets", {"id": asset_id_str})
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

        # ── 2. Warehouse & Department ──────────────────────
        warehouse = None
        department = None
        if asset.get("warehouse_id"):
            warehouse = self._fetch_one("warehouses", {"id": asset["warehouse_id"]}, columns="id,name")
        if asset.get("department_id"):
            department = self._fetch_one("departments", {"id": asset["department_id"]}, columns="id,name")

        # ── 3. Maintenance events ──────────────────────────
        maintenance = self._fetch_many(
            "maintenance_events", {"asset_id": asset_id_str},
            order_col="performed_at", order_desc=True
        )

        # ── 4. Tickets ─────────────────────────────────────
        tickets = self._fetch_many(
            "tickets", {"asset_id": asset_id_str},
            order_col="created_at", order_desc=True
        )

        # ── 5. Failure prediction ──────────────────────────
        failure_preds = self._fetch_many(
            "asset_failure_predictions", {"asset_id": asset_id_str},
            order_col="created_at", order_desc=True
        )
        failure_pred = failure_preds[0] if failure_preds else None

        # ── 6. Cost prediction ─────────────────────────────
        cost_preds = self._fetch_many(
            "asset_cost_predictions", {"asset_id": asset_id_str},
            order_col="created_at", order_desc=True
        )
        cost_pred = cost_preds[0] if cost_preds else None

        # ── 7. Sensor reading ──────────────────────────────
        sensor_readings = self._fetch_many(
            "sensor_readings", {"asset_id": asset_id_str},
            order_col="recorded_at", order_desc=True
        )
        sensor = sensor_readings[0] if sensor_readings else None

        # ── 8. Fleet-level data ────────────────────────────
        admin_summary   = _fetch_admin_summary()
        kpis            = admin_summary.get("kpis", {})
        health_dist     = admin_summary.get("healthDistribution", [])
        top_risk        = admin_summary.get("topRiskAssets", [])
        status_dist     = self._fetch_status_distribution()
        vehicle_dist    = self._fetch_vehicle_type_distribution()

        # ── 9. Maintenance metrics ─────────────────────────
        total_events   = len(maintenance)
        preventive     = sum(1 for m in maintenance if (m.get("event_type") or "").lower() == "preventive")
        corrective     = total_events - preventive
        total_cost     = sum(_float(m.get("cost_amount")) for m in maintenance)
        total_downtime = sum(_float(m.get("downtime_hours")) for m in maintenance)

        # ── 10. Ticket metrics ─────────────────────────────
        open_tickets   = [t for t in tickets if (t.get("status") or "").lower() in ("open", "in_progress")]
        high_priority  = [t for t in open_tickets if (t.get("priority") or "").lower() == "high"]
        closed_tickets = [t for t in tickets if (t.get("status") or "").lower() in ("closed", "resolved")]

        # ── 11. Prediction metrics ─────────────────────────
        health_score     = _float(failure_pred.get("health_score"))               if failure_pred else 100.0
        failure_prob     = _float(failure_pred.get("failure_probability")) * 100  if failure_pred else 0.0
        risk_level       = (failure_pred.get("risk_level") if failure_pred else None) or _band_risk(health_score)
        days_until_maint = failure_pred.get("days_until_maintenance")             if failure_pred else None
        pred_maint_date  = _date(failure_pred.get("predicted_maintenance_date"))  if failure_pred else "—"
        top_explanations = (failure_pred.get("top_explanations") or {})           if failure_pred else {}

        est_cost = _float(cost_pred.get("estimated_cost")) if cost_pred else 0.0
        min_cost = _float(cost_pred.get("min_cost"))       if cost_pred else 0.0
        max_cost = _float(cost_pred.get("max_cost"))       if cost_pred else 0.0
        currency = cost_pred.get("currency", "LKR")        if cost_pred else "LKR"

        return {
            "generated_date": datetime.now().strftime("%B %d, %Y"),
            "report_id":      asset_id_str[:8].upper(),

            # ── Fleet overview (page 1) ──────────────────
            "fleet": {
                "total_assets":         kpis.get("totalAssets", 0),
                "fleet_health":         kpis.get("fleetHealth", 0),
                "critical_alerts":      kpis.get("criticalAlerts", 0),
                "open_tickets":         kpis.get("openTickets", 0),
                "high_priority_tickets":kpis.get("highPriorityTickets", 0),
                "predicted_failures":   kpis.get("predictedFailures", 0),
                "est_maintenance_cost": kpis.get("estMaintenanceCost", 0),
                "health_distribution":  health_dist,
                "status_distribution":  status_dist,
                "vehicle_distribution": vehicle_dist,
                "top_risk_assets":      top_risk[:5],
            },

            # ── Asset core info ──────────────────────────
            "asset": {
                "id":                        _str(asset.get("id")),
                "asset_code":                _str(asset.get("asset_code")),
                "asset_name":                _str(asset.get("asset_name")),
                "asset_type":                _str(asset.get("asset_type")),
                "vehicle_type":              _str(asset.get("vehicle_type")),
                "make":                      _str(asset.get("make")),
                "model":                     _str(asset.get("model")),
                "manufacture_year":          _str(asset.get("manufacture_year")),
                "registration_number":       _str(asset.get("registration_number")),
                "vin":                       _str(asset.get("vin")),
                "status":                    _str(asset.get("status")),
                "health_band":               _str(asset.get("health_band")),
                "criticality_score":         _str(asset.get("criticality_score")),
                "purchase_date":             _date(asset.get("purchase_date")),
                "warranty_expiry_date":      _date(asset.get("warranty_expiry_date")),
                "last_service_date":         _date(asset.get("last_service_date")),
                "next_service_date":         _date(asset.get("next_service_date")),
                "current_mileage":           _str(asset.get("current_mileage")),
                "vehicle_age_years":         _str(asset.get("vehicle_age_years")),
                "payload_capacity_kg":       _str(asset.get("payload_capacity_kg")),
                "vehicle_role":              _str(asset.get("vehicle_role")),
                "lifetime_service_count":    _str(asset.get("lifetime_service_count")),
                "lifetime_breakdown_count":  _str(asset.get("lifetime_breakdown_count")),
                "description":               _str(asset.get("description")),
                "warehouse":                 _str(warehouse.get("name") if warehouse else None),
                "department":                _str(department.get("name") if department else None),
            },

            "maintenance": maintenance,
            "tickets":     tickets,

            "sensor": {
                "recorded_at":                     _datetime(sensor.get("recorded_at")),
                "tire_health_pct":                 _str(sensor.get("tire_health_pct")),
                "brake_health_pct":                _str(sensor.get("brake_health_pct")),
                "battery_health_pct":              _str(sensor.get("battery_health_pct")),
                "oil_life_pct":                    _str(sensor.get("oil_life_pct")),
                "hydraulic_health_pct":            _str(sensor.get("hydraulic_health_pct")),
                "coolant_temp_max_c":              _str(sensor.get("coolant_temp_max_c")),
                "engine_temp_avg_c":               _str(sensor.get("engine_temp_avg_c")),
                "active_fault_code_count":         _str(sensor.get("active_fault_code_count")),
                "days_since_last_service":         _str(sensor.get("days_since_last_service")),
                "engine_hours_since_last_service": _str(sensor.get("engine_hours_since_last_service")),
                "downtime_hours_last_90d":         _str(sensor.get("downtime_hours_last_90d")),
                "fuel_level":                      _str(sensor.get("fuel_level")),
                "odometer_km":                     _str(sensor.get("odometer_km")),
            } if sensor else {},

            "metrics": {
                "total_events":               total_events,
                "preventive_count":           preventive,
                "corrective_count":           corrective,
                "preventive_ratio":           round(preventive / total_events * 100, 1) if total_events else 0,
                "corrective_ratio":           round(corrective / total_events * 100, 1) if total_events else 0,
                "total_cost":                 total_cost,
                "avg_cost_per_event":         round(total_cost / total_events, 2) if total_events else 0,
                "total_downtime_hours":       round(total_downtime, 1),
                "total_tickets":              len(tickets),
                "open_tickets":               len(open_tickets),
                "high_priority_tickets":      len(high_priority),
                "closed_tickets":             len(closed_tickets),
                "health_score":               round(health_score, 1),
                "failure_probability":        round(failure_prob, 1),
                "risk_level":                 risk_level,
                "days_until_maintenance":     days_until_maint,
                "predicted_maintenance_date": pred_maint_date,
                "estimated_cost":             est_cost,
                "min_cost":                   min_cost,
                "max_cost":                   max_cost,
                "currency":                   currency,
                "top_explanations":           top_explanations,
            },
        }


def _band_risk(health_score: float) -> str:
    if health_score < 60:
        return "Critical"
    if health_score < 75:
        return "High"
    if health_score < 90:
        return "Medium"
    return "Low"