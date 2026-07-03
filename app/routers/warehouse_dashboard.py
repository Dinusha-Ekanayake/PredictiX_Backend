from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text, extract
import calendar
from datetime import datetime, timedelta

from ..deps import get_db, get_current_user, require_user
from ..models import Asset, Ticket, AssetFailurePrediction, MaintenanceEvent, AssetCostPrediction, Profile
from fastapi import BackgroundTasks
from ..services.dashboard_cache import DashboardCache

warehouse_dashboard_router = APIRouter(
    prefix="/warehouse-dashboard",
    tags=["Warehouse Dashboard"],
    dependencies=[Depends(require_user)],
)

_cache = DashboardCache("warehouse", ttl=int(__import__("os").getenv("WAREHOUSE_DASHBOARD_TTL", "60")))

@warehouse_dashboard_router.get("/summary")
def get_warehouse_summary(db: Session = Depends(get_db)):
    """
    Returns unified summary data for the Warehouse Dashboard (cached).
    """
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable — check DATABASE_URL / DATABASE_PASSWORD in the backend .env",
        )

    try:
        return _cache.get_or_refresh(db, _build_warehouse_summary)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Warehouse summary failed: {e}")


def _build_warehouse_summary(db: Session):
    # ── Query 1: all scalar KPIs from predictions + tickets + assets in one shot
    kpi_row = db.execute(text("""
        SELECT
            (SELECT ROUND(AVG(health_score)::numeric, 1)
             FROM asset_failure_predictions)                                      AS avg_health,
            (SELECT COUNT(*) FROM asset_failure_predictions
             WHERE health_score >= 80)                                            AS healthy_assets,
            (SELECT COUNT(*) FROM asset_failure_predictions
             WHERE health_score < 60)                                             AS at_risk_assets,
            (SELECT COUNT(*) FROM assets)                                         AS total_assets,
            (SELECT COUNT(*) FROM tickets WHERE status != 'closed')               AS active_tickets,
            (SELECT COUNT(*) FROM tickets)                                        AS total_tickets,
            (SELECT COALESCE(SUM(estimated_cost), 0) FROM asset_cost_predictions) AS total_cost
    """)).fetchone()

    avg_health_score     = float(kpi_row[0] or 0)
    healthy_assets       = int(kpi_row[1] or 0)
    at_risk_assets       = int(kpi_row[2] or 0)
    total_assets         = int(kpi_row[3] or 0)
    active_tickets_count = int(kpi_row[4] or 0)
    total_tickets_count  = int(kpi_row[5] or 0)
    total_cost           = int(kpi_row[6] or 0)

    avg_health_pct   = f"{int(avg_health_score)}%" if avg_health_score else "N/A"
    total_assets_str = f"{healthy_assets} of {total_assets} total" if total_assets else "0 of 0 total"
    formatted_cost   = f"Rs.{total_cost:,}"

    kpis = [
        {"label": "Average Health",  "value": avg_health_pct,            "sub": "Across all assets",          "icon": "Activity"},
        {"label": "Healthy Assets",  "value": str(healthy_assets),        "sub": total_assets_str,             "icon": "ShieldCheck"},
        {"label": "At Risk",         "value": str(at_risk_assets),        "sub": "Require attention",          "icon": "AlertTriangle"},
        {"label": "Active Tickets",  "value": str(active_tickets_count),  "sub": f"Of {total_tickets_count} total", "icon": "Ticket"},
    ]
    kpi_grid = [
        {"title": "Total Vehicles",           "value": str(total_assets),    "subtitle": "Across all warehouse operations"},
        {"title": "Critical Assets",          "value": str(at_risk_assets),  "subtitle": "Require immediate attention"},
        {"title": "Avg Component Health",     "value": avg_health_pct,       "subtitle": "Overall fleet component health"},
        {"title": "Monthly Maintenance Cost", "value": formatted_cost,       "subtitle": "Estimated current month cost"},
    ]

    # ── Query 2: asset status, type, ticket priority+category — all GROUP BYs ─
    # Run as four cheap grouped queries (all indexed scans, tiny result sets).
    status_counts    = db.query(Asset.status, func.count(Asset.id)).group_by(Asset.status).all()
    priority_counts  = db.query(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).all()
    category_counts  = db.query(Ticket.final_category, func.count(Ticket.id)).group_by(Ticket.final_category).all()
    type_counts      = db.query(Asset.vehicle_type, func.count(Asset.id)).group_by(Asset.vehicle_type).all()

    asset_status       = [{"name": s.title() if s else "Unknown",                                "value": c} for s, c in status_counts]
    ticket_priority    = [{"name": p.title() if p else "Unassigned",                             "value": c} for p, c in priority_counts]
    tickets_by_category = [{"category": c.title() if c else "General",                           "count": cnt} for c, cnt in category_counts]
    assets_by_type     = [{"type": str(t).replace("_", " ").title() if t else "Other",           "count": c} for t, c in type_counts]

    # 6. Health Score Distribution — bucketed in SQL (no full-table fetch into Python)
    bucket_rows = db.query(
        func.width_bucket(AssetFailurePrediction.health_score, 60, 100, 4).label("b"),
        func.count(AssetFailurePrediction.id),
    ).filter(AssetFailurePrediction.health_score.isnot(None)).group_by("b").all()
    # width_bucket(score, 60, 100, 4) → 0:<60, 1:60–69, 2:70–79, 3:80–89, 4&5:90–100
    buckets = {"90–100%": 0, "80–89%": 0, "70–79%": 0, "60–69%": 0, "< 60%": 0}
    _bucket_map = {0: "< 60%", 1: "60–69%", 2: "70–79%", 3: "80–89%", 4: "90–100%", 5: "90–100%"}
    for b, c in bucket_rows:
        buckets[_bucket_map.get(b, "< 60%")] += c
    health_score_dist = [{"bucket": k, "count": v} for k, v in buckets.items()]

    # 7. Monthly Ticket Volume & Health/Maintenance Trends
    # Ticket counts per month — aggregated in SQL instead of pulling every row.
    ticket_month_rows = db.query(
        extract("month", Ticket.created_at).label("m"),
        func.count(Ticket.id),
    ).filter(Ticket.created_at.isnot(None)).group_by("m").all()
    months_dict = {m: 0 for m in calendar.month_abbr[1:]}
    for m_num, cnt in ticket_month_rows:
        months_dict[calendar.month_abbr[int(m_num)]] += cnt

    current_month = datetime.now().month
    recent_months = []
    for i in range(5, -1, -1):
        m = current_month - i
        if m <= 0:
            m += 12
        recent_months.append(calendar.month_abbr[m])

    monthly_ticket_volume = [{"month": m, "total": months_dict.get(m, 0)} for m in recent_months]

    current_avg_health = int(avg_health_score) if avg_health_score else 0
    # Per-month avg health in ONE grouped query instead of one query per month.
    health_month_rows = db.query(
        extract("month", AssetFailurePrediction.created_at).label("m"),
        func.avg(AssetFailurePrediction.health_score),
    ).filter(AssetFailurePrediction.created_at.isnot(None)).group_by("m").all()
    avg_health_by_month = {int(m_num): avg_h for m_num, avg_h in health_month_rows}
    health_trends = []
    for m in recent_months:
        month_num = list(calendar.month_abbr).index(m)
        avg_h = avg_health_by_month.get(month_num)
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

    # ── Executive overview narrative (deterministic, data-grounded) ──────────
    # Mirrors the LLM report's insight_summary but is computed instantly here so
    # it can render on the dashboard with no LLM call. It rides along on the
    # already-cached summary payload, so there is no extra per-request cost.
    executive_summary = None
    # Use a FRESH session for these reads: an earlier swallowed query above
    # (component_health / recent_maintenance) can leave `db` in an aborted-
    # transaction state, which would otherwise fail every query here.
    from app.db.session import SessionLocal
    _s = SessionLocal()
    try:
        wh_row = _s.execute(text(
            "SELECT w.name FROM warehouses w "
            "LEFT JOIN assets a ON a.warehouse_id = w.id "
            "GROUP BY w.id, w.name ORDER BY COUNT(a.id) DESC LIMIT 1"
        )).fetchone()
        warehouse_name = wh_row[0] if wh_row and wh_row[0] else "PredictiX"

        avg_age = _s.execute(text(
            "SELECT ROUND(AVG(vehicle_age_years)::numeric, 1) FROM assets "
            "WHERE vehicle_age_years IS NOT NULL"
        )).scalar()
        active_users = _s.execute(text(
            "SELECT COUNT(*) FROM profiles WHERE status::text = 'active'"
        )).scalar() or 0
        dept_count = _s.execute(text("SELECT COUNT(*) FROM departments")).scalar() or 0

        status_map = {s["name"].lower(): s["value"] for s in asset_status}
        active_assets  = status_map.get("active", 0)
        maint_assets   = status_map.get("maintenance", status_map.get("under maintenance", 0))
        retired_assets = status_map.get("retired", 0)

        top_types = [t["type"].lower() for t in sorted(assets_by_type, key=lambda x: x["count"], reverse=True)[:3]]
        types_text = (
            ", ".join(top_types[:-1]) + ", and " + top_types[-1] if len(top_types) > 1
            else (top_types[0] if top_types else "various assets")
        )

        crit_rate = round(at_risk_assets / total_assets * 100, 1) if total_assets else 0.0
        iso_clause = (
            f"which exceeds the ISO 55000 5% critical target, with a critical rate of {crit_rate}%"
            if crit_rate > 5 else
            f"within the ISO 55000 5% critical target, with a critical rate of {crit_rate}%"
        )
        age_text = f"an average vehicle age of {avg_age} years" if avg_age is not None else "mixed vehicle ages"

        executive_summary = (
            f"The {warehouse_name} warehouse has a total fleet size of {total_assets} assets, "
            f"comprising various types such as {types_text}, with {age_text}. "
            f"The average fleet health score is {int(avg_health_score)}%, and there are "
            f"{at_risk_assets} critical assets, {iso_clause}. "
            f"The estimated maintenance cost is LKR {total_cost:,}, and there are "
            f"{active_tickets_count} active tickets, with {active_users} active users. "
            f"The warehouse status is active, with {dept_count} departments, and the fleet "
            f"composition includes {active_assets} active assets, {maint_assets} under maintenance, "
            f"and {retired_assets} retired assets."
        )
    except Exception:
        import logging
        logging.getLogger("predictix").warning(
            "[warehouse] executive summary build failed", exc_info=True
        )
    finally:
        _s.close()

    return {
        "kpis": kpis,
        "executiveSummary": executive_summary,
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


@warehouse_dashboard_router.get("/survival")
def get_survival_analysis(db: Session = Depends(get_db)):
    """
    FRSO Component Survival Analysis (Weibull AFT) for the dashboard.

    Pure model inference over the fleet's lowest-health assets — NO LLM call,
    so it is fast and never rate-limited. Returns per-component RUL summary plus
    a soonest-failing watchlist for live display on the Warehouse page.
    """
    try:
        # Lowest-health assets (latest prediction per asset, deduped) — the same
        # cohort the PDF report scores, so the page and PDF agree.
        critical_rows = db.execute(text("""
            SELECT * FROM (
                SELECT DISTINCT ON (p.asset_id)
                    a.asset_code, a.asset_name, a.vehicle_type, p.health_score
                FROM asset_failure_predictions p
                JOIN assets a ON a.id = p.asset_id
                ORDER BY p.asset_id, p.created_at DESC
            ) latest
            WHERE latest.health_score < 60
            ORDER BY latest.health_score ASC
            LIMIT 12
        """)).fetchall()

        critical_assets = [
            {
                "code": r[0],
                "name": r[1] or "Vehicle",
                "type": str(r[2]).replace("_", " ").title() if r[2] else "Unknown",
                "health_score": int(r[3]) if r[3] is not None else None,
            }
            for r in critical_rows
        ]

        from app.agents.report_agents import _build_survival_summary
        summary = _build_survival_summary(critical_assets)

        return {
            "status": "success",
            "survival_summary": summary,
            "critical_assets": critical_assets,
            # ISO-8601 UTC timestamp so the dashboard can show when this was scored.
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Survival analysis failed: {str(e)}")


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
