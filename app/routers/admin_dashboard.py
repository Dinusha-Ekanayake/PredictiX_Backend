"""Admin Dashboard router — single aggregate endpoint for the admin overview.

GET /admin-dashboard/summary returns a fully-shaped JSON payload the frontend
is already typed against. Every list may be empty and every number may be 0;
the frontend degrades gracefully. All values come from the real DB via a few
aggregate queries + a handful of small .limit() lists (no N+1 loops).

Mirrors the style of warehouse_dashboard.py (raw SQLAlchemy aggregates,
try/except -> HTTPException).
"""
from __future__ import annotations

import calendar
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..deps import get_db
from ..models import (
    Asset,
    AssetCostPrediction,
    AssetFailurePrediction,
    MaintenanceEvent,
    Notification,
    Profile,
    Ticket,
    Warehouse,
)

admin_dashboard_router = APIRouter(prefix="/admin-dashboard", tags=["Admin Dashboard"])


def _months_ending_at(anchor: datetime, n: int) -> list[tuple[int, int, str]]:
    """Return [(year, month, 'Mon'), ...] oldest->newest for the trailing n
    months ending at the anchor month (inclusive). Year rollover is handled."""
    out: list[tuple[int, int, str]] = []
    for i in range(n - 1, -1, -1):
        m = anchor.month - i
        y = anchor.year
        while m <= 0:
            m += 12
            y -= 1
        out.append((y, m, calendar.month_abbr[m]))
    return out


@admin_dashboard_router.get("/summary")
def get_admin_summary(db: Session = Depends(get_db)):
    """Unified summary data for the Admin Dashboard (real DB data)."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        return _build_admin_summary(db)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Admin dashboard failed: {e}")


def _build_admin_summary(db: Session):
    # ── KPIs ────────────────────────────────────────────────────────────────
    total_assets = db.query(func.count(Asset.id)).scalar() or 0

    from sqlalchemy import case, and_

    pred_stats = db.query(
        func.sum(case((AssetFailurePrediction.health_score < 60, 1), else_=0)),
        func.avg(AssetFailurePrediction.health_score),
        func.sum(case((AssetFailurePrediction.failure_probability >= 0.5, 1), else_=0)),
        func.sum(case((AssetFailurePrediction.health_score >= 90, 1), else_=0)),
        func.sum(case((and_(AssetFailurePrediction.health_score >= 75, AssetFailurePrediction.health_score < 90), 1), else_=0)),
        func.sum(case((and_(AssetFailurePrediction.health_score >= 60, AssetFailurePrediction.health_score < 75), 1), else_=0)),
        func.sum(case((and_(AssetFailurePrediction.health_score >= 40, AssetFailurePrediction.health_score < 60), 1), else_=0)),
        func.sum(case((AssetFailurePrediction.health_score < 40, 1), else_=0))
    ).first()

    critical_alerts = int(pred_stats[0] or 0) if pred_stats else 0
    avg_health = pred_stats[1] if pred_stats else None
    fleet_health = int(round(float(avg_health))) if avg_health is not None else 0
    predicted_failures = int(pred_stats[2] or 0) if pred_stats else 0

    band_excellent = int(pred_stats[3] or 0) if pred_stats else 0
    band_good = int(pred_stats[4] or 0) if pred_stats else 0
    band_moderate = int(pred_stats[5] or 0) if pred_stats else 0
    band_poor = int(pred_stats[6] or 0) if pred_stats else 0
    band_critical = int(pred_stats[7] or 0) if pred_stats else 0

    ticket_stats = db.query(
        func.sum(case((text("status != 'closed'"), 1), else_=0)),
        func.sum(case((text("priority = 'high' AND status != 'closed'"), 1), else_=0)),
        func.max(Ticket.created_at),
        func.sum(case((text("status IN ('resolved','closed')"), 1), else_=0)),
        func.avg(
            case(
                (text("closed_at IS NOT NULL AND created_at IS NOT NULL"), 
                 func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 86400.0),
                else_=None
            )
        )
    ).first()

    open_tickets = int(ticket_stats[0] or 0) if ticket_stats else 0
    high_priority_tickets = int(ticket_stats[1] or 0) if ticket_stats else 0
    ticket_anchor_dt = ticket_stats[2] if ticket_stats and ticket_stats[2] else datetime.now()
    tickets_resolved = int(ticket_stats[3] or 0) if ticket_stats else 0
    avg_resolution = ticket_stats[4]

    est_cost = db.query(func.sum(AssetCostPrediction.estimated_cost)).scalar()
    est_maintenance_cost = int(est_cost) if est_cost else 0

    kpis = {
        "totalAssets": int(total_assets),
        "criticalAlerts": int(critical_alerts),
        "openTickets": int(open_tickets),
        "highPriorityTickets": int(high_priority_tickets),
        "fleetHealth": fleet_health,
        "predictedFailures": int(predicted_failures),
        "estMaintenanceCost": est_maintenance_cost,
    }

    # ── Anchor windows to the LATEST month that actually has data ─────────────
    # (the newest real data is months behind server "now", so anchoring to now()
    #  would produce empty trailing months and clip the real data).
    now = datetime.now()

    maint_anchor_dt = db.query(func.max(MaintenanceEvent.performed_at)).scalar() or now

    ticket_months = _months_ending_at(ticket_anchor_dt, 6)
    cost_months = _months_ending_at(maint_anchor_dt, 6)

    # ── healthTrend (anchored to the maintenance window) ──────────────────────
    # No historical health snapshots in DB (predictions are single-dated);
    # using real current fleet average as the baseline.
    health_trend = []
    for (_, _, abbr) in cost_months:
        health_trend.append({"month": abbr, "avgHealth": int(fleet_health)})

    # ── ticketTrend (grouped by month of created_at) ──────────────────────────
    ticket_rows = (
        db.query(
            func.to_char(Ticket.created_at, "YYYY-MM").label("ym"),
            Ticket.status,
            func.count(Ticket.id),
        )
        .filter(Ticket.created_at.isnot(None))
        .group_by("ym", Ticket.status)
        .all()
    )
    # ym -> {opened, inProgress, resolved}
    ticket_by_ym: dict[str, dict[str, int]] = {}
    for ym, status, cnt in ticket_rows:
        bucket = ticket_by_ym.setdefault(ym, {"opened": 0, "inProgress": 0, "resolved": 0})
        bucket["opened"] += cnt
        if status == "in_progress":
            bucket["inProgress"] += cnt
        if status in ("resolved", "closed"):
            bucket["resolved"] += cnt

    ticket_trend = []
    for y, m, abbr in ticket_months:
        ym = f"{y:04d}-{m:02d}"
        b = ticket_by_ym.get(ym, {"opened": 0, "inProgress": 0, "resolved": 0})
        ticket_trend.append(
            {
                "period": abbr,
                "opened": int(b["opened"]),
                "inProgress": int(b["inProgress"]),
                "resolved": int(b["resolved"]),
            }
        )

    # ── healthDistribution (best -> worst) ───────────────────────────────────
    health_distribution = [
        {"name": "Excellent", "count": band_excellent},
        {"name": "Good", "count": band_good},
        {"name": "Moderate", "count": band_moderate},
        {"name": "Poor", "count": band_poor},
        {"name": "Critical", "count": band_critical},
    ]

    # ── costTrend (trailing months ending at latest maintenance month) ───────
    # estimated = preventive (planned) maintenance cost that month
    # actual    = total real maintenance cost that month (null for current month)
    cost_rows = (
        db.query(
            func.to_char(MaintenanceEvent.performed_at, "YYYY-MM").label("ym"),
            func.sum(MaintenanceEvent.cost_amount).label("total"),
            func.sum(
                func.coalesce(
                    text(
                        "CASE WHEN maintenance_events.event_type = 'preventive' "
                        "THEN maintenance_events.cost_amount ELSE 0 END"
                    ),
                    0,
                )
            ).label("planned"),
        )
        .filter(MaintenanceEvent.performed_at.isnot(None))
        .group_by("ym")
        .all()
    )
    cost_by_ym = {ym: (planned, total) for ym, total, planned in cost_rows}
    current_ym = f"{now.year:04d}-{now.month:02d}"
    cost_trend = []
    for y, m, abbr in cost_months:
        ym = f"{y:04d}-{m:02d}"
        planned, total = cost_by_ym.get(ym, (None, None))
        estimated = int(planned) if planned else 0
        actual = None if ym == current_ym else (int(total) if total else 0)
        cost_trend.append({"month": abbr, "estimated": estimated, "actual": actual})

    # ── downtimeByWarehouse (planned=preventive, unplanned=repair) ───────────
    downtime_rows = (
        db.query(
            Warehouse.name,
            MaintenanceEvent.event_type,
            func.sum(MaintenanceEvent.downtime_hours),
        )
        .join(Asset, MaintenanceEvent.asset_id == Asset.id)
        .join(Warehouse, Asset.warehouse_id == Warehouse.id)
        .filter(MaintenanceEvent.downtime_hours.isnot(None))
        .group_by(Warehouse.name, MaintenanceEvent.event_type)
        .all()
    )
    dt_by_wh: dict[str, dict[str, float]] = {}
    for name, etype, hours in downtime_rows:
        wh = dt_by_wh.setdefault(name or "Unknown", {"planned": 0.0, "unplanned": 0.0})
        if etype == "preventive":
            wh["planned"] += float(hours or 0)
        else:
            wh["unplanned"] += float(hours or 0)
    downtime_by_warehouse = [
        {"warehouse": name, "planned": round(v["planned"]), "unplanned": round(v["unplanned"])}
        for name, v in dt_by_wh.items()
    ]

    # ── topRiskAssets (worst health first; one prediction per asset in DB) ────
    risk_rows = (
        db.query(Asset, AssetFailurePrediction, Warehouse.name)
        .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id)
        .outerjoin(Warehouse, Asset.warehouse_id == Warehouse.id)
        .order_by(AssetFailurePrediction.health_score.asc())
        .limit(8)
        .all()
    )
    today = datetime.now().date()
    top_risk_assets = []
    for asset, pred, wh_name in risk_rows:
        days_to_maint = None
        if asset.next_service_date:
            days_to_maint = (asset.next_service_date - today).days
        top_risk_assets.append(
            {
                "id": asset.asset_code or str(asset.id),
                "name": asset.asset_name or asset.model or "Asset",
                "location": wh_name or "Unknown",
                "healthScore": int(round(float(pred.health_score))) if pred.health_score is not None else 0,
                "failureProbability": float(pred.failure_probability) if pred.failure_probability is not None else 0.0,
                "daysToMaintenance": days_to_maint,
            }
        )

    # ── recentAlerts (latest 5 notifications) ────────────────────────────────
    # Explicit columns only (the full Notification entity is risky if the ORM and
    # DB schema drift). Severity is derived from the notification type/status.
    def _severity_for(ntype: str | None, nstatus: str | None) -> str:
        t = f"{ntype or ''} {nstatus or ''}".lower()
        if any(k in t for k in ("alert", "critical", "failure", "high_risk", "urgent")):
            return "critical"
        if any(k in t for k in ("warning", "maintenance", "risk", "due")):
            return "warning"
        return "info"

    notif_rows = (
        db.query(
            Notification.id,
            Notification.type,
            Notification.status,
            Notification.title,
            Notification.message,
            Notification.created_at,
            Asset.asset_name,
            Warehouse.name,
        )
        .outerjoin(Asset, Notification.related_asset_id == Asset.id)
        .outerjoin(Warehouse, Asset.warehouse_id == Warehouse.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )
    recent_alerts = []
    for nid, ntype, nstatus, ntitle, nmessage, ncreated, asset_name, wh_name in notif_rows:
        recent_alerts.append(
            {
                "id": str(nid),
                "severity": _severity_for(ntype, nstatus),
                # Real value either way: asset name when linked, else the title.
                "asset": asset_name or ntitle or "System",
                "location": (wh_name or "Unknown") if asset_name else "Fleet-wide",
                "message": nmessage or ntitle or "",
                "createdAt": ncreated.isoformat() if ncreated else None,
            }
        )

    # ── latestTickets (latest 5 by created_at) ───────────────────────────────
    assignee = Profile.__table__.alias("assignee")
    ticket_list_rows = (
        db.query(
            Ticket.id,
            Ticket.ticket_number,
            Ticket.title,
            Ticket.priority,
            Ticket.final_priority,
            Ticket.status,
            Asset.asset_name,
            assignee.c.full_name,
        )
        .outerjoin(Asset, Ticket.asset_id == Asset.id)
        .outerjoin(assignee, Ticket.assigned_to == assignee.c.id)
        .order_by(Ticket.created_at.desc())
        .limit(5)
        .all()
    )
    valid_priorities = {"critical", "high", "medium", "low"}
    valid_statuses = {"open", "in_progress", "resolved", "closed"}
    latest_tickets = []
    for tid, tnum, ttitle, tprio, tfprio, tstatus, asset_name, assignee_name in ticket_list_rows:
        prio = (tfprio or tprio or "medium").lower()
        if prio not in valid_priorities:
            prio = "medium"
        status = (tstatus or "open").lower()
        if status not in valid_statuses:
            status = "open"
        latest_tickets.append(
            {
                "id": tnum or str(tid)[:8],
                "title": ttitle or "Untitled",
                "asset": asset_name or "—",
                "priority": prio,
                "status": status,
                "assignedTo": assignee_name or "—",
            }
        )

    # ── footerStats ──────────────────────────────────────────────────────────
    avg_resolution_days = round(float(avg_resolution), 1) if avg_resolution else 0.0

    footer_stats = {
        "avgHealthScore": fleet_health,
        "ticketsResolved": int(tickets_resolved),
        "avgResolutionDays": avg_resolution_days,
    }

    # ── aiInsights (rule-based, derived from the numbers) ─────────────────────
    ai_insights = []
    if critical_alerts > 0:
        ai_insights.append(
            {
                "tone": "critical",
                "title": "Critical assets need attention",
                "body": f"{critical_alerts} assets are below 60% health and should be prioritised for inspection.",
            }
        )
    if high_priority_tickets > 0:
        ai_insights.append(
            {
                "tone": "warning",
                "title": "High-priority tickets open",
                "body": f"{high_priority_tickets} high-priority tickets are still open and awaiting resolution.",
            }
        )
    if predicted_failures > 0:
        ai_insights.append(
            {
                "tone": "warning",
                "title": "Predicted failures ahead",
                "body": f"{predicted_failures} assets have a failure probability of 50% or higher.",
            }
        )
    if fleet_health >= 75:
        ai_insights.append(
            {
                "tone": "positive",
                "title": "Fleet health is strong",
                "body": f"Average fleet health is {fleet_health}%, above the healthy threshold.",
            }
        )
    ai_insights = ai_insights[:4]

    # ── aiSummary (LLM if available, else a real KPI-derived fallback) ────────
    # Always returns a real, data-grounded string — never null and never blocks.
    # We skip the synchronous LLM call here because it causes the dashboard to hang for 5-10s on load.
    ai_summary: str | None = None

    if not ai_summary:
        ai_summary = (
            f"Fleet health averages {fleet_health}% across {int(total_assets)} assets. "
            f"{int(critical_alerts)} assets are at risk and {int(predicted_failures)} are "
            f"predicted to fail within the maintenance horizon. "
            f"{int(open_tickets)} tickets are open ({int(high_priority_tickets)} high priority). "
            f"Estimated maintenance cost is Rs.{est_maintenance_cost:,}."
        )

    return {
        "kpis": kpis,
        "healthTrend": health_trend,
        "ticketTrend": ticket_trend,
        "healthDistribution": health_distribution,
        "costTrend": cost_trend,
        "downtimeByWarehouse": downtime_by_warehouse,
        "topRiskAssets": top_risk_assets,
        "recentAlerts": recent_alerts,
        "latestTickets": latest_tickets,
        "footerStats": footer_stats,
        "aiSummary": ai_summary,
        "aiInsights": ai_insights,
    }
