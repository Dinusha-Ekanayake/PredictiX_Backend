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
import logging
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

log = logging.getLogger("predictix")

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
from ..services.health_bands import (
    CRITICAL_THRESHOLD,
    HEALTH_BAND_NAMES,
    band_count_sql,
)
from ..services.maintenance_classification import planned_value, unplanned_value

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
    # "Critical Alerts" previously counted health_score < 60 — which is
    # actually Poor (40-59) + Critical (<40) combined, per the health
    # distribution bands computed in this same query. That inflated the KPI
    # card (438) far above what the "Critical" band in the Health
    # Distribution chart on the same page shows (267) — the same word
    # meaning two different things on one screen. Now uses the same <40
    # cutoff as h_critical below, so the headline number and the chart
    # agree.
    pred_agg = db.execute(text(f"""
        SELECT
            COUNT(*)                                                        AS total_preds,
            COUNT(*) FILTER (WHERE health_score < {CRITICAL_THRESHOLD})     AS critical_alerts,
            ROUND(AVG(health_score)::numeric, 2)                            AS avg_health,
            COUNT(*) FILTER (WHERE failure_probability >= 0.5)              AS predicted_failures,
            -- Bands generated from app.services.health_bands, the single
            -- definition shared with assets.health_band, so the same fleet
            -- can never be reported two different ways on two screens.
            {band_count_sql()}
        FROM pdm_batch_predictions
        WHERE status = 'ok' AND health_score IS NOT NULL AND {_assets_in}
    """), _wh).fetchone()

    total_preds         = int(pred_agg[0] or 0)
    critical_alerts     = int(pred_agg[1] or 0)
    avg_health_raw      = pred_agg[2]
    fleet_health        = int(round(float(avg_health_raw))) if avg_health_raw is not None else 0
    predicted_failures  = int(pred_agg[3] or 0)
    # A brand-new warehouse with zero PdM predictions run yet would show
    # "0% Fleet Health" indistinguishable from a real, alarming 0% score —
    # this flag lets the frontend show a distinct "no predictions yet"
    # empty state instead of a false alarm.
    has_prediction_data = total_preds > 0
    # Bands come back in the same best->worst order band_count_sql() emitted,
    # starting at index 4 (after total/critical/avg/predicted_failures).
    health_distribution = [
        {"name": name.capitalize(), "count": int(pred_agg[4 + i] or 0)}
        for i, name in enumerate(HEALTH_BAND_NAMES)
    ]

    # ── Query 2: all ticket aggregates + anchors in one pass ──────────────────
    # Real ticket_status enum: open, in_progress, pending, resolved, closed,
    # cancelled. "Open" (operationally still needs attention) excludes both
    # closed AND cancelled — a cancelled ticket isn't open, but the previous
    # `status != 'closed'` counted it (and inflated the "Open Tickets" KPI/
    # banner). Resolution time now falls back to resolved_at when closed_at
    # isn't set yet, so a ticket sitting in "resolved" status (already
    # counted in tickets_resolved) isn't silently excluded from the
    # avg-resolution-days sample that stat is paired with in the footer.
    ticket_agg = db.execute(text(f"""
        SELECT
            COUNT(*) FILTER (WHERE status NOT IN ('closed', 'cancelled'))       AS open_tickets,
            COUNT(*) FILTER (WHERE priority = 'high' AND status NOT IN ('closed', 'cancelled')) AS high_priority,
            COUNT(*) FILTER (WHERE status IN ('resolved','closed'))              AS tickets_resolved,
            ROUND(AVG(
                CASE WHEN COALESCE(closed_at, resolved_at) IS NOT NULL AND created_at IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (COALESCE(closed_at, resolved_at) - created_at)) / 86400.0
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
             WHERE status = 'ok' AND {_assets_in})                    AS est_cost,
            -- SUM skips NULLs, and estimated_cost_lkr is NULL whenever the cost
            -- model could not score an asset (it no longer substitutes a
            -- heuristic guess). Without a coverage count a broken cost model
            -- would just look like a cheaper fleet, so report how many assets
            -- the total actually covers and let the UI qualify it.
            (SELECT COUNT(*)
             FROM pdm_batch_predictions
             WHERE status = 'ok' AND estimated_cost_lkr IS NOT NULL
               AND {_assets_in})                                      AS costed_assets
    """), _wh).fetchone()

    total_assets          = int(misc_agg[0] or 0)
    maint_anchor_dt       = misc_agg[1] or now
    est_maintenance_cost  = int(misc_agg[2] or 0)
    costed_assets         = int(misc_agg[3] or 0)

    # health_distribution's 5 bands only cover assets with a completed
    # ('ok', non-null health_score) prediction — an asset with a failed
    # prediction run (status='no_data') or no pdm_batch_predictions row at
    # all falls into none of them. That silently made the chart's total
    # (sum of the 5 bands) diverge from totalAssets shown elsewhere on the
    # same dashboard (e.g. 1065 vs 1073), reading as "the numbers don't
    # match" rather than "8 assets haven't been scored yet". Add an explicit
    # band for them so every asset is accounted for exactly once.
    unclassified = max(total_assets - total_preds, 0)
    if unclassified > 0:
        health_distribution.append({"name": "No Data", "count": unclassified})

    kpis = {
        "totalAssets":        total_assets,
        "criticalAlerts":     critical_alerts,
        "openTickets":        open_tickets,
        "highPriorityTickets": high_priority_tickets,
        "fleetHealth":        fleet_health,
        "predictedFailures":  predicted_failures,
        "estMaintenanceCost": est_maintenance_cost,
        # How many assets the figure above is actually built from. When this is
        # below totalAssets the total is partial, not a lower fleet spend.
        "estMaintenanceCostAssetCount": costed_assets,
        "hasPredictionData":  has_prediction_data,
    }
    footer_stats = {
        "avgHealthScore":    fleet_health,
        "ticketsResolved":   tickets_resolved,
        "avgResolutionDays": avg_resolution_days,
    }

    # ── Anchor windows to the LATEST month that actually has data ─────────────
    ticket_months = _months_ending_at(ticket_anchor_dt, 6)
    cost_months   = _months_ending_at(maint_anchor_dt, 6)

    # ── healthTrend (real historical data, not fabricated) ────────────────────
    # Previously this repeated the single CURRENT fleet_health value across all
    # 6 months — a flat line with no real variation, inconsistent with the
    # ticket/cost/downtime trends right next to it on the same page, which all
    # plot genuine historical data (#99). pdm_batch_predictions can't supply
    # real history: it's an upsert table, one row per asset, latest score
    # only. pdm_prediction_history is the append-only log the batch job has
    # actually been writing to since 2026-07-10 (5000+ real rows) — use that
    # instead. Months with no recorded predictions get a null gap in the line
    # rather than an invented number; if there's no history at all yet, the
    # array comes back empty so the frontend's existing "No health-trend
    # data." state shows instead of a misleadingly blank chart.
    _health_hist_rows = db.execute(text(f"""
        SELECT to_char(h.predicted_at, 'YYYY-MM') AS ym,
               AVG(h.health_score)                AS avg_health,
               MAX(h.predicted_at)                 AS latest
        FROM pdm_prediction_history h
        WHERE h.health_score IS NOT NULL
          AND h.asset_id IN (SELECT id FROM assets {_assets_where})
        GROUP BY ym
    """), _wh).fetchall()

    health_by_ym = {r[0]: float(r[1]) for r in _health_hist_rows}
    if health_by_ym:
        health_anchor_dt = max(r[2] for r in _health_hist_rows)
        health_trend = [
            {"month": abbr, "avgHealth": round(health_by_ym[f"{y:04d}-{m:02d}"], 1) if f"{y:04d}-{m:02d}" in health_by_ym else None}
            for (y, m, abbr) in _months_ending_at(health_anchor_dt, 6)
        ]
    else:
        health_trend = []

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
        # "opened" = every ticket created that month regardless of current
        # status (a running total, not a same-kind category alongside the
        # other two) — inProgress/resolved are subsets of it by CURRENT
        # status, not separate buckets that sum to it. Every real status
        # (open, in_progress, pending, resolved, closed, cancelled) is now
        # accounted for in at least the "opened" total; previously "open"/
        # "pending"/"cancelled" tickets silently contributed to "opened"
        # but had no bucket of their own at all.
        b = ticket_by_ym.setdefault(ym, {"opened": 0, "inProgress": 0, "resolved": 0})
        b["opened"] += cnt
        if status in ("in_progress", "pending"):
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

    # ── Query 5: cost trend grouped by month (planned vs unplanned spend) ────
    # Previously this reported "estimated" (only event_type='preventive') vs
    # "actual" (every event). Two problems: 'preventive' is used by no row in
    # this database, so the estimated series was a flat zero line; and the pair
    # was mislabelled — both numbers are money already spent, so "estimated vs
    # actual" described a budget-vs-outturn comparison the data cannot support
    # (no budget is stored anywhere).
    #
    # Now it splits real spend by whether the work was planned, using the same
    # classification as the downtime chart below so the two agree. Reactive
    # spend is the figure a maintenance operation is actually managed against.
    _cost_q = (
        db.query(
            func.to_char(MaintenanceEvent.performed_at, "YYYY-MM").label("ym"),
            func.sum(planned_value(MaintenanceEvent.cost_amount)).label("planned"),
            func.sum(unplanned_value(MaintenanceEvent.cost_amount)).label("unplanned"),
        )
        .filter(MaintenanceEvent.performed_at.isnot(None))
    )
    if warehouse_id:
        _cost_q = _cost_q.join(Asset, MaintenanceEvent.asset_id == Asset.id).filter(
            Asset.warehouse_id == warehouse_id
        )
    cost_rows = _cost_q.group_by("ym").all()
    cost_by_ym = {ym: (planned, unplanned) for ym, planned, unplanned in cost_rows}
    cost_trend = []
    for y, m, abbr in cost_months:
        planned, unplanned = cost_by_ym.get(f"{y:04d}-{m:02d}", (None, None))
        # Both series are the same kind of measure, so the current (partial)
        # month is shown for both rather than blanking one of them — nulling
        # only one made the newest month look like a collapse in spend.
        cost_trend.append({
            "month":     abbr,
            "planned":   int(planned or 0),
            "unplanned": int(unplanned or 0),
        })

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
                func.sum(planned_value(MaintenanceEvent.downtime_hours)).label("planned"),
                func.sum(unplanned_value(MaintenanceEvent.downtime_hours)).label("unplanned"),
            )
            .join(Asset, MaintenanceEvent.asset_id == Asset.id)
            .filter(
                MaintenanceEvent.downtime_hours.isnot(None),
                MaintenanceEvent.performed_at.isnot(None),
                Asset.warehouse_id == warehouse_id,
            )
            .group_by("ym")
        )
        dt_by_key: dict[str, dict[str, float]] = {
            ym: {"planned": float(planned or 0), "unplanned": float(unplanned or 0)}
            for ym, planned, unplanned in _dt_q.all()
        }
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
                func.sum(planned_value(MaintenanceEvent.downtime_hours)).label("planned"),
                func.sum(unplanned_value(MaintenanceEvent.downtime_hours)).label("unplanned"),
            )
            .join(Asset, MaintenanceEvent.asset_id == Asset.id)
            .join(Warehouse, Asset.warehouse_id == Warehouse.id)
            .filter(MaintenanceEvent.downtime_hours.isnot(None))
            .group_by(Warehouse.name)
        )
        downtime_by_warehouse = [
            {
                "warehouse": name or "Unknown",
                "planned":   round(float(planned or 0)),
                "unplanned": round(float(unplanned or 0)),
            }
            for name, planned, unplanned in _dt_q.all()
        ]
        downtime_scope = "warehouse"

    # ── Query 7: top 8 risk assets (worst health first) ───────────────────────
    # Wrapped: this is a secondary widget, not core to the dashboard. A
    # failure here (e.g. a transient join issue) previously 500'd the ENTIRE
    # dashboard — contradicting this module's own docstring promise that
    # "every list may be empty... frontend degrades gracefully."
    top_risk_assets: list[dict] = []
    try:
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
    except Exception:
        log.warning("Admin dashboard: top-risk-assets query failed (non-fatal)", exc_info=True)

    # ── Query 8: recent alerts (latest 5 notifications) ───────────────────────
    def _severity_for(ntype: str | None, nstatus: str | None) -> str:
        t = f"{ntype or ''} {nstatus or ''}".lower()
        if any(k in t for k in ("alert", "critical", "failure", "high_risk", "urgent")):
            return "critical"
        if any(k in t for k in ("warning", "maintenance", "risk", "due")):
            return "warning"
        return "info"

    recent_alerts: list[dict] = []
    try:
        # notifications.user_id is NOT NULL — every row is addressed to one
        # specific person, so this is a personal inbox table, not a shared
        # fleet-alerts feed. This endpoint's response is cached per-WAREHOUSE
        # (DashboardCache), not per-user, so it cannot be filtered to "the
        # viewing admin's own notifications" without leaking whichever admin's
        # request happened to trigger the cache build to every other admin
        # sharing that warehouse — that would trade one cross-tenant leak for a
        # worse one. Restricted to notifications addressed to an admin/
        # super_admin role instead, which keeps this a fleet-oversight feed
        # (not an arbitrary technician's personal notification) while staying
        # correctly shareable across everyone viewing the same cached payload.
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
            .join(Profile, Notification.user_id == Profile.id)
            .filter(Profile.role.in_(("admin", "super_admin")))
            .outerjoin(Asset, Notification.related_asset_id == Asset.id)
            .outerjoin(Warehouse, Asset.warehouse_id == Warehouse.id)
        )
        if warehouse_id:
            # Two ways an alert belongs on this warehouse's dashboard:
            #   * it is about an asset here, or
            #   * it is not about any asset, but was addressed to someone who
            #     works here (or to a global super admin, who has no warehouse).
            #
            # The second clause used to be just `related_asset_id IS NULL`,
            # which let every asset-less notification through no matter whose
            # warehouse the recipient belonged to. Because these are ordered
            # newest-first and capped at 5, one warehouse's recent activity
            # filled all five slots on every other warehouse's dashboard —
            # verified: Colombo and Badulla were each showing 5 of 5 alerts
            # addressed to Galle staff, hiding their own.
            _notif_q = _notif_q.filter(
                (Asset.warehouse_id == warehouse_id)
                | (
                    Notification.related_asset_id.is_(None)
                    & (
                        (Profile.warehouse_id == warehouse_id)
                        | Profile.warehouse_id.is_(None)
                    )
                )
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
    except Exception:
        log.warning("Admin dashboard: recent-alerts query failed (non-fatal)", exc_info=True)

    # ── Query 9: latest 5 tickets ─────────────────────────────────────────────
    latest_tickets: list[dict] = []
    try:
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
        for tid, tnum, ttitle, tprio, tfprio, tstatus, asset_name, assignee_name in ticket_list_rows:
            prio   = (tfprio or tprio or "medium").lower()
            status = (tstatus or "open").lower()
            latest_tickets.append({
                "id":         tnum or str(tid)[:8],
                # Real ticket UUID — "id" above is the human-readable
                # ticket_number (display label), not a usable identifier.
                # The frontend needs this to navigate to the actual ticket.
                "ticketId":   str(tid),
                "title":      ttitle or "Untitled",
                "asset":      asset_name or "—",
                "priority":   prio   if prio   in valid_priorities else "medium",
                "status":     status if status in valid_statuses   else "open",
                "assignedTo": assignee_name or "—",
            })
    except Exception:
        log.warning("Admin dashboard: latest-tickets query failed (non-fatal)", exc_info=True)

    # ── aiInsights (rule-based, derived from the numbers) ─────────────────────
    ai_insights = []
    if critical_alerts > 0:
        ai_insights.append(
            {
                "tone": "critical",
                "title": "Critical assets need attention",
                "body": (
                    f"{critical_alerts} assets are below {CRITICAL_THRESHOLD:g}% health "
                    f"and should be prioritised for inspection."
                ),
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

    # ── aiSummary (data-grounded, deterministic — no LLM call here) ───────────
    # This card previously tried to serve a live-cached Groq summary
    # (run_warehouse_agent) behind `if warehouse_id is None`, but the only
    # caller of this function always resolves a real warehouse via
    # active_warehouse_id() — which raises rather than ever returning None —
    # so that branch could never run. It wasn't a bug in the LLM integration
    # itself (run_warehouse_agent works and is warehouse-scoped correctly;
    # see the user-triggered "Full report" flow in warehouse_dashboard.py,
    # which calls the same function and produces real output), it was just
    # dead code left after the scoping model changed.
    #
    # Deliberately not re-wiring it as a live per-request/TTL cache: Groq's
    # call volume is limited, and it's better spent on user-initiated
    # requests (chatbot, "Full report") than an always-on background timer
    # nobody explicitly asked for. This card stays a plain, honest,
    # zero-cost data summary — the frontend already labels it "Data summary"
    # rather than claiming it's AI-generated.
    #
    # Cheap upgrade path if real AI text is wanted here later: generate it
    # once a day inside the existing scheduled batch job (one Groq call per
    # warehouse per day) and persist it, rather than any live cache.
    ai_summary_is_generated = False

    # The cost sentence has to survive a cost model that scored none or only
    # some of the fleet. Stating a partial sum as "the" estimated cost would
    # under-report fleet spend with nothing to indicate why, so the sentence
    # says what it covers — or says the estimate is unavailable and stops.
    if costed_assets == 0:
        cost_sentence = "Estimated maintenance cost is unavailable — the cost model has not scored any assets."
    elif costed_assets < total_assets:
        cost_sentence = (
            f"Estimated maintenance cost is Rs.{est_maintenance_cost:,} across the "
            f"{costed_assets} of {int(total_assets)} assets the cost model could score."
        )
    else:
        cost_sentence = f"Estimated maintenance cost is Rs.{est_maintenance_cost:,}."

    ai_summary = (
        f"Fleet health averages {fleet_health}% across {int(total_assets)} assets. "
        f"{int(critical_alerts)} assets are at risk and {int(predicted_failures)} are "
        f"predicted to fail within the maintenance horizon. "
        f"{int(open_tickets)} tickets are open ({int(high_priority_tickets)} high priority). "
        f"{cost_sentence}"
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
        "aiSummaryIsGenerated": ai_summary_is_generated,
        "aiInsights": ai_insights,
    }
