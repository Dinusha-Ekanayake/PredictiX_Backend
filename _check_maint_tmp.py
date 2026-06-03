"""One-off: confirm the maintenance reporting window now lands on real data."""
from app.db.session import SessionLocal
from sqlalchemy import func
from app.models import MaintenanceEvent, Ticket
from app.agents.report_agents import build_warehouse_context

db = SessionLocal()
try:
    print("max(performed_at) maintenance:", db.query(func.max(MaintenanceEvent.performed_at)).scalar())
    print("max(created_at) tickets     :", db.query(func.max(Ticket.created_at)).scalar())
    print("total maintenance rows      :", db.query(func.count(MaintenanceEvent.id)).scalar())
    ctx = build_warehouse_context(db)
    print("\n--- report window now ---")
    print("period                :", ctx["period"], "| current?", ctx.get("reporting_window_current"))
    print("total_maintenance_3m  :", ctx["total_maintenance_events_3m"])
    print("actual_cost_3m        :", ctx["actual_cost_3m"])
    print("avg_downtime_hours    :", ctx["avg_downtime_hours"])
    print("monthly_maintenance   :", ctx["monthly_maintenance_trend"])
finally:
    db.close()
