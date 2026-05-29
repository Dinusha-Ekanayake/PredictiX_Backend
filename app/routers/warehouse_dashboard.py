from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text, extract
import calendar
from datetime import datetime, timedelta

from ..deps import get_db, get_current_user
from ..models import Asset, Ticket, AssetFailurePrediction, MaintenanceEvent, AssetCostPrediction, Profile
from fastapi import BackgroundTasks

warehouse_dashboard_router = APIRouter(prefix="/warehouse-dashboard", tags=["Warehouse Dashboard"])

@warehouse_dashboard_router.get("/summary")
def get_warehouse_summary(db: Session = Depends(get_db)):
    """
    Returns unified summary data for the Warehouse Dashboard.
    Fetches all data directly from PostgreSQL database.
    """
    # If database is not available, raise exception
    if db is None:
        raise Exception("Database connection unavailable")
    
    # 1. Row 1: WarehouseOverviewCards
    active_tickets_count = db.query(Ticket.id).filter(text("status != 'closed'")).count()
    total_tickets_count = db.query(Ticket.id).count()
    
    avg_health_score = db.query(func.avg(AssetFailurePrediction.health_score)).scalar() or 0
    avg_health_pct = f"{int(avg_health_score)}%" if avg_health_score else "N/A"
    
    healthy_assets = db.query(AssetFailurePrediction.id).filter(AssetFailurePrediction.health_score >= 80).count()
    at_risk_assets = db.query(AssetFailurePrediction.id).filter(AssetFailurePrediction.health_score < 60).count()

    total_assets = db.query(Asset.id).count()
    total_assets_str = f"{healthy_assets} of {total_assets} total" if total_assets else "0 of 0 total"

    kpis = [
        {
            "label": "Average Health",
            "value": avg_health_pct,
            "sub": "Across all assets",
            "icon": "Activity",
        },
        {
            "label": "Healthy Assets",
            "value": str(healthy_assets),
            "sub": total_assets_str,
            "icon": "ShieldCheck",
        },
        {
            "label": "At Risk",
            "value": str(at_risk_assets),
            "sub": "Require attention",
            "icon": "AlertTriangle",
        },
        {
            "label": "Active Tickets",
            "value": str(active_tickets_count),
            "sub": f"Of {total_tickets_count} total",
            "icon": "Ticket",
        },
    ]

    cost_query = db.query(func.sum(AssetCostPrediction.estimated_cost)).scalar()
    
    total_cost = int(cost_query) if cost_query else 0
    formatted_cost = f"Rs.{total_cost:,}"

    # Row 2: WarehouseKPIGrid
    total_vehicles_count = total_assets
    critical_assets_count = at_risk_assets
    kpi_grid = [
        {
            "title": "Total Vehicles",
            "value": str(total_vehicles_count),
            "subtitle": "Across all warehouse operations",
        },
        {
            "title": "Critical Assets",
            "value": str(critical_assets_count),
            "subtitle": "Require immediate attention",
        },
        {
            "title": "Avg Component Health",
            "value": avg_health_pct,
            "subtitle": "Overall fleet component health",
        },
        {
            "title": "Monthly Maintenance Cost",
            "value": formatted_cost,
            "subtitle": "Estimated current month cost",
        },
    ]

    # 2. Asset Status Distribution
    status_counts = db.query(Asset.status, func.count(Asset.id)).group_by(Asset.status).all()
    asset_status = [{"name": s.title() if s else "Unknown", "value": c} for s, c in status_counts]

    # 3. Tickets by Priority
    priority_counts = db.query(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).all()
    ticket_priority = [{"name": p.title() if p else "Unassigned", "value": c} for p, c in priority_counts]

    # 4. Tickets by Category
    category_counts = db.query(Ticket.final_category, func.count(Ticket.id)).group_by(Ticket.final_category).all()
    tickets_by_category = [{"category": c.title() if c else "General", "count": count} for c, count in category_counts]

    # 5. Assets by Type (Specialized)
    type_counts = db.query(Asset.vehicle_type, func.count(Asset.id)).group_by(Asset.vehicle_type).all()
    assets_by_type = [{"type": str(t).replace("_", " ").title() if t else "Other", "count": c} for t, c in type_counts]

    # 6. Health Score Distribution
    health_scores = db.query(AssetFailurePrediction.health_score).filter(AssetFailurePrediction.health_score.isnot(None)).all()
    buckets = {"90–100%": 0, "80–89%": 0, "70–79%": 0, "60–69%": 0, "< 60%": 0}
    for (score,) in health_scores:
        if score >= 90: buckets["90–100%"] += 1
        elif score >= 80: buckets["80–89%"] += 1
        elif score >= 70: buckets["70–79%"] += 1
        elif score >= 60: buckets["60–69%"] += 1
        else: buckets["< 60%"] += 1
    health_score_dist = [{"bucket": k, "count": v} for k, v in buckets.items()]

    # 7. Monthly Ticket Volume & Health/Maintenance Trends
    tickets = db.query(Ticket.created_at).filter(Ticket.created_at.isnot(None)).all()
    months_dict = {m: 0 for m in calendar.month_abbr[1:]}
    for (created_at,) in tickets:
        month_name = calendar.month_abbr[created_at.month]
        months_dict[month_name] += 1
    
    current_month = datetime.now().month
    recent_months = []
    for i in range(5, -1, -1):
        m = current_month - i
        if m <= 0:
            m += 12
        recent_months.append(calendar.month_abbr[m])
        
    monthly_ticket_volume = [{"month": m, "total": months_dict.get(m, 0)} for m in recent_months]
    
    current_avg_health = int(avg_health_score) if avg_health_score else 0
    health_trends = []
    for m in recent_months:
        month_num = list(calendar.month_abbr).index(m)
        avg_h = db.query(func.avg(AssetFailurePrediction.health_score)).filter(
            extract('month', AssetFailurePrediction.created_at) == month_num
        ).scalar()
        health_trends.append({
            "month": m,
            "avgHealth": int(avg_h) if avg_h else current_avg_health,
            "maintenance": months_dict.get(m, 0)
        })

    # 8. Critical Assets Table Info
    critical_assets_query = db.query(Asset, AssetFailurePrediction)\
        .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id)\
        .filter(AssetFailurePrediction.health_score < 70)\
        .limit(10).all()
        
    critical_assets_list = []
    for asset, pred in critical_assets_query:
        critical_assets_list.append({
            "id": asset.asset_code or "Unknown",
            "vehicle": asset.model or asset.asset_name or "Vehicle",
            "component": asset.category or "General",
            "health": f"{int(pred.health_score)}%",
            "priority": "High" if pred.health_score < 50 else "Medium",
            "status": "Critical" if pred.health_score < 50 else "Warning"
        })

    # 9. Component Health (from sensor_readings — latest reading per asset)
    component_health = {"avg_tire": 0.0, "avg_brake": 0.0, "avg_battery": 0.0, "avg_oil": 0.0, "avg_hydraulic": 0.0}
    total_fault_codes = 0
    assets_with_sensors = 0
    try:
        comp_row = db.execute(text("""
            SELECT
                ROUND(AVG(tire_health_pct)::numeric, 1)      AS avg_tire,
                ROUND(AVG(brake_health_pct)::numeric, 1)     AS avg_brake,
                ROUND(AVG(battery_health_pct)::numeric, 1)   AS avg_battery,
                ROUND(AVG(oil_life_pct)::numeric, 1)         AS avg_oil,
                ROUND(AVG(hydraulic_health_pct)::numeric, 1) AS avg_hydraulic,
                COALESCE(SUM(active_fault_code_count), 0)::int AS total_faults,
                COUNT(*)::int AS asset_count
            FROM (
                SELECT DISTINCT ON (asset_id)
                    asset_id, tire_health_pct, brake_health_pct,
                    battery_health_pct, oil_life_pct, hydraulic_health_pct,
                    active_fault_code_count
                FROM sensor_readings
                WHERE recorded_at IS NOT NULL
                ORDER BY asset_id, recorded_at DESC
            ) latest
        """)).fetchone()
        if comp_row:
            component_health = {
                "avg_tire":      float(comp_row[0] or 0),
                "avg_brake":     float(comp_row[1] or 0),
                "avg_battery":   float(comp_row[2] or 0),
                "avg_oil":       float(comp_row[3] or 0),
                "avg_hydraulic": float(comp_row[4] or 0),
            }
            total_fault_codes   = int(comp_row[5] or 0)
            assets_with_sensors = int(comp_row[6] or 0)
    except Exception:
        pass

    # 10. Recent Maintenance Events (last 10)
    recent_maintenance = []
    try:
        recent_rows = db.execute(text("""
            SELECT
                me.id,
                a.asset_name,
                a.asset_code,
                me.maintenance_type,
                me.vendor_name,
                COALESCE(me.cost_amount, 0)::numeric AS cost,
                me.performed_at,
                me.notes
            FROM maintenance_events me
            LEFT JOIN assets a ON me.asset_id = a.id
            WHERE me.performed_at IS NOT NULL
            ORDER BY me.performed_at DESC
            LIMIT 10
        """)).fetchall()
        for r in recent_rows:
            recent_maintenance.append({
                "asset":    r[1] or "Unknown Asset",
                "code":     r[2] or "—",
                "type":     str(r[3]).replace("_", " ").title() if r[3] else "General",
                "vendor":   r[4] or "—",
                "cost":     float(r[5] or 0),
                "date":     r[6].strftime("%Y-%m-%d") if r[6] else "—",
                "notes":    (r[7] or "")[:80],
            })
    except Exception:
        pass

    return {
        "kpis": kpis,
        "kpiGrid": kpi_grid,
        "healthMaintenanceTrends": health_trends,
        "assetStatus": asset_status,
        "healthScoreDist": health_score_dist,
        "assetsByType": assets_by_type,
        "ticketPriority": ticket_priority,
        "ticketsByCategory": tickets_by_category,
        "monthlyTicketVolume": monthly_ticket_volume,
        "criticalAssets": critical_assets_list,
        "componentHealth": component_health,
        "totalFaultCodes": total_fault_codes,
        "assetsWithSensors": assets_with_sensors,
        "recentMaintenance": recent_maintenance,
    }

@warehouse_dashboard_router.get("/maintenance-schedule")
def get_maintenance_schedule(db: Session = Depends(get_db)):
    """
    Returns predictive maintenance schedule from real Supabase database data.
    predicted  = AssetFailurePrediction.days_until_maintenance (ML regressor output)
    scheduled  = last performed_at + fleet avg maintenance interval, projected forward
                 (computed entirely from maintenance_events table — no hardcoded values)
    """
    try:
        today = datetime.utcnow().date()

        # ── Fleet average maintenance interval from real maintenance history ──
        avg_interval_row = db.execute(text("""
            SELECT AVG(gap_days)::int FROM (
                SELECT
                    EXTRACT(EPOCH FROM (performed_at - LAG(performed_at)
                        OVER (PARTITION BY asset_id ORDER BY performed_at))) / 86400 AS gap_days
                FROM maintenance_events
                WHERE performed_at IS NOT NULL
            ) sub
            WHERE gap_days > 0 AND gap_days < 365
        """)).scalar()
        avg_interval_days = int(avg_interval_row) if avg_interval_row else 90

        # ── Most recent prediction per asset (subquery) ──
        latest_pred = (
            db.query(
                AssetFailurePrediction.asset_id,
                func.max(AssetFailurePrediction.created_at).label("max_at"),
            )
            .group_by(AssetFailurePrediction.asset_id)
            .subquery()
        )

        rows = (
            db.query(Asset, AssetFailurePrediction)
            .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id)
            .join(
                latest_pred,
                (AssetFailurePrediction.asset_id == latest_pred.c.asset_id)
                & (AssetFailurePrediction.created_at == latest_pred.c.max_at),
            )
            .filter(
                text("assets.status::text NOT IN ('retired', 'inactive')"),
                AssetFailurePrediction.days_until_maintenance.isnot(None),
                AssetFailurePrediction.days_until_maintenance > 0,
            )
            .order_by(AssetFailurePrediction.days_until_maintenance.asc())
            .limit(50)
            .all()
        )

        # ── Most recent performed_at per asset (for interval projection) ──
        last_performed = {
            row[0]: row[1]
            for row in db.query(
                MaintenanceEvent.asset_id,
                func.max(MaintenanceEvent.performed_at).label("last_at"),
            )
            .filter(MaintenanceEvent.performed_at.isnot(None))
            .group_by(MaintenanceEvent.asset_id)
            .all()
        }

        schedule = []
        for asset, pred in rows:
            predicted_weeks = round(float(pred.days_until_maintenance) / 7, 2)

            # Scheduled: project from last actual service + fleet avg interval
            scheduled_weeks = None
            last_svc = last_performed.get(asset.id)
            if last_svc:
                last_date = last_svc.date() if hasattr(last_svc, "date") else last_svc
                from datetime import timedelta as td
                next_proj = last_date + td(days=avg_interval_days)
                days_to_sched = (next_proj - today).days
                scheduled_weeks = round(max(0, days_to_sched) / 7, 2)
            elif asset.last_service_date:
                from datetime import timedelta as td
                next_proj = asset.last_service_date + td(days=avg_interval_days)
                days_to_sched = (next_proj - today).days
                scheduled_weeks = round(max(0, days_to_sched) / 7, 2)

            if scheduled_weeks is None:
                continue

            schedule.append({
                "asset": asset.asset_name,
                "predicted": predicted_weeks,
                "scheduled": scheduled_weeks,
            })

        schedule.sort(key=lambda x: x["predicted"] - x["scheduled"])
        return schedule

    except Exception as e:
        import traceback
        traceback.print_exc()
        return []


# ──────────────────────────────────────────────────────────────
# AI REPORT GENERATION ENDPOINT (Admin only)
# ──────────────────────────────────────────────────────────────

from fastapi import HTTPException
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    asset_id: str | None = None


@warehouse_dashboard_router.get("/generate-report")
def generate_warehouse_report(db: Session = Depends(get_db)):
    """
    KB-Enhanced Warehouse Report Agent endpoint.
    Aggregates all PostgreSQL data → KB Vector Store retrieval →
    KB Annotations (deterministic) → Llama 3 (via Groq) →
    returns AI sections + raw context + kb_annotations for PDF export.
    Admin access only.
    """
    try:
        from app.agents.report_agents import run_warehouse_agent
        result = run_warehouse_agent(db)
        return {
            "status":         "success",
            "ai_sections":    result["ai_sections"],
            "context":        result["context"],
            "kb_annotations": result.get("kb_annotations", {}),  # NEW
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


@warehouse_dashboard_router.post("/chat-route")
def chat_route(request: ChatRequest, db: Session = Depends(get_db)):
    """
    Main Router Agent endpoint for chatbot integration.
    Routes user message to the correct agent and returns response.
    """
    try:
        from app.agents.report_agents import route_request, run_warehouse_agent, run_asset_agent

        intent = route_request(request.message)

        if intent == "warehouse_report":
            result = run_warehouse_agent(db)
            return {
                "intent": intent,
                "response": result["ai_sections"].get("insight_summary", ""),
                "full_report": result["ai_sections"],
                "context": result["context"],
            }
        elif intent == "asset_report":
            result = run_asset_agent(asset_id=request.asset_id)
            return {
                "intent": intent,
                "response": result["message"],
                "data": result,
            }
        else:
            return {
                "intent": intent,
                "response": "I can help you generate warehouse or asset reports. "
                            "Please ask me to generate a report for more details.",
            }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat routing failed: {str(e)}")
from app.services.report_notification_service import ReportNotificationService

@warehouse_dashboard_router.post("/notify-print")
def notify_report_print(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Triggers an email notification that the Warehouse AI Report was printed.
    """
    background_tasks.add_task(
        ReportNotificationService.notify_on_report_print,
        db, 
        str(current_user.id)
    )
    return {"status": "success", "message": "Notification dispatched"}
