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

from ..deps import get_db, require_admin, get_current_user, active_warehouse_id
from ..models import (
    Asset,
    MaintenanceEvent,
    Notification,
    PdmBatchPrediction,
    Profile,
    Ticket,
    Warehouse,
)
from ..services.dashboard_cache import DashboardCache

admin_dashboard_router = APIRouter(
    prefix="/admin-dashboard",
    tags=["Admin Dashboard"],
    dependencies=[Depends(require_admin)],
)

_cache = DashboardCache("admin", ttl=int(__import__("os").getenv("ADMIN_DASHBOARD_TTL", "60")))


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
def get_admin_summary(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Unified summary data for the Admin Dashboard (real DB data, cached).

    Scoped to the caller's active warehouse: a regular admin sees their own
    warehouse; a super_admin sees the warehouse selected at login. Cache is
    keyed per warehouse.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    wh_id = active_warehouse_id(current_user)
    try:
        return _cache.get_or_refresh(
            db,
            lambda d: _build_admin_summary(d, wh_id),
            key=wh_id,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Admin dashboard failed: {e}")


def _build_admin_summary(db: Session, warehouse_id: str | None = None):
    now = datetime.now()

    # Warehouse scoping: entities with no warehouse column of their own
    # (predictions, costs, maintenance) are scoped via their asset's warehouse.
    _wh = {"wh": warehouse_id} if warehouse_id else {}
    _assets_in = (
        "asset_id IN (SELECT id FROM assets WHERE warehouse_id = :wh)"
        if warehouse_id else "TRUE"
    )
    _assets_where = "WHERE warehouse_id = :wh" if warehouse_id else ""
    _tickets_where = "WHERE warehouse_id = :wh" if warehouse_id else ""

    # ── Query 1: all pdm_batch_predictions aggregates in one pass ──────────────
    # pdm_batch_predictions is the single source of truth for PdM output
    # (populated by the daily scheduler + the asset-page "Run AI" trigger) —
    # asset_failure_predictions was the old on-demand-only table, unused by
    # the asset detail page since the v7/decision-layer unification and left
    # stale here (~1 month old) until this fix.
    pred_agg = db.execute(text(f"""
        SELECT
            COUNT(*)                                                        AS total_preds,
            COUNT(*) FILTER (WHERE health_score < 60)                       AS critical_alerts,
            ROUND(AVG(health_score)::numeric, 2)                            AS avg_health,
            COUNT(*) FILTER (WHERE failure_probability >= 0.5)              AS predicted_failures,
            -- health distribution bands (Excellent/Good/Moderate/Poor/Critical)
            COUNT(*) FILTER (WHERE health_score >= 90)                      AS h_excellent,
            COUNT(*) FILTER (WHERE health_score >= 75 AND health_score < 90) AS h_good,
            COUNT(*) FILTER (WHERE health_score >= 60 AND health_score < 75) AS h_moderate,
            COUNT(*) FILTER (WHERE health_score >= 40 AND health_score < 60) AS h_poor,
            COUNT(*) FILTER (WHERE health_score < 40)                       AS h_critical
        FROM pdm_batch_predictions
        WHERE status = 'ok' AND health_score IS NOT NULL AND {_assets_in}
    """), _wh).fetchone()

    critical_alerts     = int(pred_agg[1] or 0)
    avg_health_raw      = pred_agg[2]
    fleet_health        = int(round(float(avg_health_raw))) if avg_health_raw is not None else 0
    predicted_failures  = int(pred_agg[3] or 0)
    health_distribution = [
        {"name": "Excellent", "count": int(pred_agg[4] or 0)},
        {"name": "Good",      "count": int(pred_agg[5] or 0)},
        {"name": "Moderate",  "count": int(pred_agg[6] or 0)},
        {"name": "Poor",      "count": int(pred_agg[7] or 0)},
        {"name": "Critical",  "count": int(pred_agg[8] or 0)},
    ]

    # ── Query 2: all ticket aggregates + anchors in one pass ──────────────────
    ticket_agg = db.execute(text(f"""
        SELECT
            COUNT(*) FILTER (WHERE status != 'closed')                          AS open_tickets,
            COUNT(*) FILTER (WHERE priority = 'high' AND status != 'closed')    AS high_priority,
            COUNT(*) FILTER (WHERE status IN ('resolved','closed'))              AS tickets_resolved,
            ROUND(AVG(
                CASE WHEN closed_at IS NOT NULL AND created_at IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (closed_at - created_at)) / 86400.0
                END
            )::numeric, 1)                                                       AS avg_resolution_days,
            MAX(created_at)                                                      AS max_created_at
        FROM tickets
        {_tickets_where}
    """), _wh).fetchone()

    open_tickets       = int(ticket_agg[0] or 0)
    high_priority_tickets = int(ticket_agg[1] or 0)
    tickets_resolved   = int(ticket_agg[2] or 0)
    avg_resolution_days = float(ticket_agg[3] or 0)
    ticket_anchor_dt   = ticket_agg[4] or now

    # ── Query 3: assets total + maintenance anchor + cost ─────────────────────
    misc_agg = db.execute(text(f"""
        SELECT
            (SELECT COUNT(*) FROM assets {_assets_where})             AS total_assets,
            (SELECT MAX(performed_at) FROM maintenance_events
             WHERE {_assets_in})                                      AS max_maint_at,
            (SELECT COALESCE(SUM(estimated_cost_lkr), 0)
             FROM pdm_batch_predictions
             WHERE status = 'ok' AND {_assets_in})                    AS est_cost
    """), _wh).fetchone()

    total_assets          = int(misc_agg[0] or 0)
    maint_anchor_dt       = misc_agg[1] or now
    est_maintenance_cost  = int(misc_agg[2] or 0)

    kpis = {
        "totalAssets":        total_assets,
        "criticalAlerts":     critical_alerts,
        "openTickets":        open_tickets,
        "highPriorityTickets": high_priority_tickets,
        "fleetHealth":        fleet_health,
        "predictedFailures":  predicted_failures,
        "estMaintenanceCost": est_maintenance_cost,
    }
    footer_stats = {
        "avgHealthScore":    fleet_health,
        "ticketsResolved":   tickets_resolved,
        "avgResolutionDays": avg_resolution_days,
    }

    # ── Anchor windows to the LATEST month that actually has data ─────────────
    ticket_months = _months_ending_at(ticket_anchor_dt, 6)
    cost_months   = _months_ending_at(maint_anchor_dt, 6)

    # ── healthTrend ───────────────────────────────────────────────────────────
    health_trend = [{"month": abbr, "avgHealth": fleet_health} for (_, _, abbr) in cost_months]

    # ── Query 4: ticket trend grouped by month×status ─────────────────────────
    _tt_q = (
        db.query(
            func.to_char(Ticket.created_at, "YYYY-MM").label("ym"),
            Ticket.status,
            func.count(Ticket.id),
        )
        .filter(Ticket.created_at.isnot(None))
    )
    if warehouse_id:
        _tt_q = _tt_q.filter(Ticket.warehouse_id == warehouse_id)
    ticket_rows = _tt_q.group_by("ym", Ticket.status).all()
    ticket_by_ym: dict[str, dict[str, int]] = {}
    for ym, status, cnt in ticket_rows:
        b = ticket_by_ym.setdefault(ym, {"opened": 0, "inProgress": 0, "resolved": 0})
        b["opened"] += cnt
        if status == "in_progress":
            b["inProgress"] += cnt
        if status in ("resolved", "closed"):
            b["resolved"] += cnt

    ticket_trend = []
    for y, m, abbr in ticket_months:
        ym = f"{y:04d}-{m:02d}"
        b = ticket_by_ym.get(ym, {"opened": 0, "inProgress": 0, "resolved": 0})
        ticket_trend.append({
            "period":     abbr,
            "opened":     int(b["opened"]),
            "inProgress": int(b["inProgress"]),
            "resolved":   int(b["resolved"]),
        })

    # ── Query 5: cost trend grouped by month (total + preventive) ────────────
    _cost_q = (
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
    )
    if warehouse_id:
        _cost_q = _cost_q.join(Asset, MaintenanceEvent.asset_id == Asset.id).filter(
            Asset.warehouse_id == warehouse_id
        )
    cost_rows = _cost_q.group_by("ym").all()
    cost_by_ym = {ym: (planned, total) for ym, total, planned in cost_rows}
    current_ym = f"{now.year:04d}-{now.month:02d}"
    cost_trend = []
    for y, m, abbr in cost_months:
        ym = f"{y:04d}-{m:02d}"
        planned, total = cost_by_ym.get(ym, (None, None))
        estimated = int(planned) if planned else 0
        actual = None if ym == current_ym else (int(total) if total else 0)
        cost_trend.append({"month": abbr, "estimated": estimated, "actual": actual})

    # ── Query 6: downtime planned vs unplanned ───────────────────────────────
    # Unscoped (fleet view): grouped BY WAREHOUSE so warehouses can be compared.
    # Scoped to one warehouse: a single-warehouse bar is meaningless, so instead
    # group BY MONTH (last 6 months) to show that warehouse's downtime trend.
    # Both shapes keep the same output keys ({label, planned, unplanned}) so the
    # frontend chart renders either without change; only the axis label differs.
    if warehouse_id:
        _dt_q = (
            db.query(
                func.to_char(MaintenanceEvent.performed_at, "YYYY-MM").label("ym"),
                MaintenanceEvent.event_type,
                func.sum(MaintenanceEvent.downtime_hours),
            )
            .join(Asset, MaintenanceEvent.asset_id == Asset.id)
            .filter(
                MaintenanceEvent.downtime_hours.isnot(None),
                MaintenanceEvent.performed_at.isnot(None),
                Asset.warehouse_id == warehouse_id,
            )
            .group_by("ym", MaintenanceEvent.event_type)
        )
        dt_by_key: dict[str, dict[str, float]] = {}
        for ym, etype, hours in _dt_q.all():
            bucket = dt_by_key.setdefault(ym, {"planned": 0.0, "unplanned": 0.0})
            if etype == "preventive":
                bucket["planned"] += float(hours or 0)
            else:
                bucket["unplanned"] += float(hours or 0)
        # Emit the trailing 6 months in order, labelled by month abbreviation.
        downtime_by_warehouse = []
        for y, m, abbr in _months_ending_at(maint_anchor_dt, 6):
            v = dt_by_key.get(f"{y:04d}-{m:02d}", {"planned": 0.0, "unplanned": 0.0})
            downtime_by_warehouse.append(
                {"warehouse": abbr, "planned": round(v["planned"]), "unplanned": round(v["unplanned"])}
            )
        downtime_scope = "month"
    else:
        _dt_q = (
            db.query(
                Warehouse.name,
                MaintenanceEvent.event_type,
                func.sum(MaintenanceEvent.downtime_hours),
            )
            .join(Asset, MaintenanceEvent.asset_id == Asset.id)
            .join(Warehouse, Asset.warehouse_id == Warehouse.id)
            .filter(MaintenanceEvent.downtime_hours.isnot(None))
            .group_by(Warehouse.name, MaintenanceEvent.event_type)
        )
        dt_by_wh: dict[str, dict[str, float]] = {}
        for name, etype, hours in _dt_q.all():
            wh = dt_by_wh.setdefault(name or "Unknown", {"planned": 0.0, "unplanned": 0.0})
            if etype == "preventive":
                wh["planned"] += float(hours or 0)
            else:
                wh["unplanned"] += float(hours or 0)
        downtime_by_warehouse = [
            {"warehouse": name, "planned": round(v["planned"]), "unplanned": round(v["unplanned"])}
            for name, v in dt_by_wh.items()
        ]
        downtime_scope = "warehouse"

    # ── Query 7: top 8 risk assets (worst health first) ───────────────────────
    _risk_q = (
        db.query(Asset, PdmBatchPrediction, Warehouse.name)
        .join(PdmBatchPrediction, Asset.id == PdmBatchPrediction.asset_id)
        .outerjoin(Warehouse, Asset.warehouse_id == Warehouse.id)
        .filter(PdmBatchPrediction.status == "ok")
    )
    if warehouse_id:
        _risk_q = _risk_q.filter(Asset.warehouse_id == warehouse_id)
    risk_rows = _risk_q.order_by(PdmBatchPrediction.health_score.asc()).limit(8).all()
    today = now.date()
    top_risk_assets = []
    for asset, pred, wh_name in risk_rows:
        days_to_maint = (asset.next_service_date - today).days if asset.next_service_date else None
        top_risk_assets.append({
            # Real asset UUID — the frontend uses this to navigate to the
            # asset detail page. asset_code is shown separately as the
            # human-readable label, not used as an identifier.
            "id":               str(asset.id),
            "code":             asset.asset_code,
            "name":             asset.asset_name or asset.model or "Asset",
            "location":         wh_name or "Unknown",
            "healthScore":      int(round(float(pred.health_score))) if pred.health_score is not None else 0,
            "failureProbability": float(pred.failure_probability) if pred.failure_probability is not None else 0.0,
            "daysToMaintenance": days_to_maint,
        })

    # ── Query 8: recent alerts (latest 5 notifications) ───────────────────────
    def _severity_for(ntype: str | None, nstatus: str | None) -> str:
        t = f"{ntype or ''} {nstatus or ''}".lower()
        if any(k in t for k in ("alert", "critical", "failure", "high_risk", "urgent")):
            return "critical"
        if any(k in t for k in ("warning", "maintenance", "risk", "due")):
            return "warning"
        return "info"

    _notif_q = (
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
    )
    if warehouse_id:
        # Keep this warehouse's asset-linked alerts plus system/fleet-wide alerts
        # that aren't tied to any asset (so system notices still show).
        _notif_q = _notif_q.filter(
            (Asset.warehouse_id == warehouse_id)
            | (Notification.related_asset_id.is_(None))
        )
    notif_rows = _notif_q.order_by(Notification.created_at.desc()).limit(5).all()
    recent_alerts = [
        {
            "id":       str(nid),
            "severity": _severity_for(ntype, nstatus),
            "asset":    asset_name or ntitle or "System",
            "location": (wh_name or "Unknown") if asset_name else "Fleet-wide",
            "message":  nmessage or ntitle or "",
            "createdAt": ncreated.isoformat() if ncreated else None,
        }
        for nid, ntype, nstatus, ntitle, nmessage, ncreated, asset_name, wh_name in notif_rows
    ]

    # ── Query 9: latest 5 tickets ─────────────────────────────────────────────
    assignee = Profile.__table__.alias("assignee")
    _tl_q = (
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
    )
    if warehouse_id:
        _tl_q = _tl_q.filter(Ticket.warehouse_id == warehouse_id)
    ticket_list_rows = _tl_q.order_by(Ticket.created_at.desc()).limit(5).all()
    valid_priorities = {"critical", "high", "medium", "low"}
    valid_statuses   = {"open", "in_progress", "resolved", "closed"}
    latest_tickets = []
    for tid, tnum, ttitle, tprio, tfprio, tstatus, asset_name, assignee_name in ticket_list_rows:
        prio   = (tfprio or tprio or "medium").lower()
        status = (tstatus or "open").lower()
        latest_tickets.append({
            "id":         tnum or str(tid)[:8],
            "title":      ttitle or "Untitled",
            "asset":      asset_name or "—",
            "priority":   prio   if prio   in valid_priorities else "medium",
            "status":     status if status in valid_statuses   else "open",
            "assignedTo": assignee_name or "—",
        })

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

    # ── aiSummary (cached LLM, never blocks) ──────────────────────────────────
    # The LLM (run_warehouse_agent → Groq, 3–10s + ~50 DB queries) is NEVER
    # called inline here. Instead we serve the most recent LLM summary from a
    # short-TTL in-memory cache and kick off a background refresh when it goes
    # stale. Until the first refresh lands (or if the LLM is unavailable) we fall
    # back to the instant, data-grounded KPI summary below — so the dashboard is
    # always sub-second and the AI text appears automatically once ready.
    from app.services.ai_summary_cache import get_cached_summary, maybe_refresh

    maybe_refresh()  # non-blocking; no-op if fresh or already running
    ai_summary = get_cached_summary()

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
        "downtimeScope": downtime_scope,  # "warehouse" (fleet) or "month" (scoped)
        "topRiskAssets": top_risk_assets,
        "recentAlerts": recent_alerts,
        "latestTickets": latest_tickets,
        "footerStats": footer_stats,
        "aiSummary": ai_summary,
        "aiInsights": ai_insights,
    }
