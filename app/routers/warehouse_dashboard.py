from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text, extract
import calendar
import logging
from datetime import datetime, timedelta

from ..deps import get_db, get_current_user, require_user, active_warehouse_id
from ..models import Department

log = logging.getLogger("predictix")
from ..models import Asset, Ticket, PdmBatchPrediction, PdmPredictionHistory, MaintenanceEvent, Profile
from fastapi import BackgroundTasks
from ..services.dashboard_cache import DashboardCache

warehouse_dashboard_router = APIRouter(
    prefix="/warehouse-dashboard",
    tags=["Warehouse Dashboard"],
    dependencies=[Depends(require_user)],
)

_cache = DashboardCache("warehouse", ttl=int(__import__("os").getenv("WAREHOUSE_DASHBOARD_TTL", "60")))
_survival_cache = DashboardCache("warehouse_survival", ttl=int(__import__("os").getenv("WAREHOUSE_DASHBOARD_TTL", "60")))


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

@warehouse_dashboard_router.get("/summary")
def get_warehouse_summary(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    Returns unified summary data for the Warehouse Dashboard (cached).

    Scoped to the caller's active warehouse: a regular admin sees their own
    warehouse; a super_admin sees the warehouse they selected at login. The
    cache is keyed per warehouse so views never bleed across warehouses.
    """
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable — check DATABASE_URL / DATABASE_PASSWORD in the backend .env",
        )

    wh_id = active_warehouse_id(current_user)
    try:
        return _cache.get_or_refresh(
            db,
            lambda d: _build_warehouse_summary(d, wh_id),
            key=wh_id,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Warehouse summary failed: {e}")


def _build_warehouse_summary(db: Session, warehouse_id: str | None = None):
    # When a warehouse is set (admin / super_admin), every metric below is
    # restricted to that warehouse. Entities that have no warehouse column of
    # their own (predictions, costs, sensors, maintenance) are scoped through
    # their asset's warehouse via asset_id IN (assets of this warehouse).
    #   _wh          -> bind param dict (empty when unscoped)
    #   _assets_in   -> SQL predicate string for asset-linked tables
    _wh = {"wh": warehouse_id} if warehouse_id else {}
    _assets_in = (
        "asset_id IN (SELECT id FROM assets WHERE warehouse_id = :wh)"
        if warehouse_id else "TRUE"
    )
    _assets_where = "WHERE warehouse_id = :wh" if warehouse_id else ""
    _tickets_where = "WHERE warehouse_id = :wh" if warehouse_id else ""
    _tickets_and = "warehouse_id = :wh AND" if warehouse_id else ""

    # ── Query 1: all scalar KPIs from predictions + tickets + assets in one shot
    # pdm_batch_predictions is the single source of truth for PdM output
    # (populated by the daily scheduler + the asset-page "Run AI" trigger),
    # upserted with exactly one row per asset — unlike the old
    # asset_failure_predictions/asset_cost_predictions tables this replaced,
    # there's no "latest of several rows" history to DISTINCT ON here.
    # asset_failure_predictions/asset_cost_predictions were superseded by
    # pdm_batch_predictions since the v7/decision-layer unification and
    # never written to since — reading from them here silently produced
    # stale/empty KPIs regardless of how current the real predictions were.
    kpi_row = db.execute(text(f"""
        SELECT
            (SELECT ROUND(AVG(health_score)::numeric, 1) FROM pdm_batch_predictions
             WHERE status = 'ok' AND {_assets_in})                                 AS avg_health,
            (SELECT COUNT(*) FROM pdm_batch_predictions
             WHERE status = 'ok' AND {_assets_in} AND health_score >= 70)          AS healthy_assets,
            (SELECT COUNT(*) FROM pdm_batch_predictions
             WHERE status = 'ok' AND {_assets_in} AND health_score < 60)           AS at_risk_assets,
            (SELECT COUNT(*) FROM assets {_assets_where})                          AS total_assets,
            (SELECT COUNT(*) FROM tickets WHERE {_tickets_and} status != 'closed') AS active_tickets,
            (SELECT COUNT(*) FROM tickets {_tickets_where})                        AS total_tickets,
            (SELECT COALESCE(SUM(estimated_cost_lkr), 0) FROM pdm_batch_predictions
             WHERE status = 'ok' AND {_assets_in})                                 AS total_cost
    """), _wh).fetchone()

    avg_health_score     = float(kpi_row[0] or 0)
    healthy_assets       = int(kpi_row[1] or 0)
    at_risk_assets       = int(kpi_row[2] or 0)
    total_assets         = int(kpi_row[3] or 0)
    active_tickets_count = int(kpi_row[4] or 0)
    total_tickets_count  = int(kpi_row[5] or 0)
    total_cost           = int(kpi_row[6] or 0)

    avg_health_pct   = f"{avg_health_score:.1f}%" if avg_health_score else "N/A"
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
    _asset_q  = db.query(Asset.status, func.count(Asset.id))
    _type_q   = db.query(Asset.vehicle_type, func.count(Asset.id))
    _prio_q   = db.query(Ticket.priority, func.count(Ticket.id))
    _cat_q    = db.query(Ticket.final_category, func.count(Ticket.id))
    if warehouse_id:
        _asset_q = _asset_q.filter(Asset.warehouse_id == warehouse_id)
        _type_q  = _type_q.filter(Asset.warehouse_id == warehouse_id)
        _prio_q  = _prio_q.filter(Ticket.warehouse_id == warehouse_id)
        _cat_q   = _cat_q.filter(Ticket.warehouse_id == warehouse_id)
    status_counts    = _asset_q.group_by(Asset.status).all()
    priority_counts  = _prio_q.group_by(Ticket.priority).all()
    category_counts  = _cat_q.group_by(Ticket.final_category).all()
    type_counts      = _type_q.group_by(Asset.vehicle_type).all()

    asset_status       = [{"name": s.title() if s else "Unknown",                                "value": c} for s, c in status_counts]
    ticket_priority    = [{"name": p.title() if p else "Unassigned",                             "value": c} for p, c in priority_counts]
    tickets_by_category = [{"category": c.title(),                                               "count": cnt} for c, cnt in category_counts if c is not None]
    assets_by_type     = [{"type": str(t).replace("_", " ").title() if t else "Other",           "count": c} for t, c in type_counts]

    # 6. Health Score Distribution — bucketed in SQL over pdm_batch_predictions,
    # which already holds exactly one (current) row per asset.
    _bucket_where = (
        "p.asset_id IN (SELECT id FROM assets WHERE warehouse_id = :wh) AND "
        if warehouse_id else ""
    )
    bucket_rows = db.execute(text(f"""
        SELECT width_bucket(health_score, 60, 100, 4) AS b, COUNT(*)
        FROM pdm_batch_predictions p
        WHERE {_bucket_where}p.status = 'ok' AND p.health_score IS NOT NULL
        GROUP BY b
    """), _wh).fetchall()
    # width_bucket(score, 60, 100, 4) → 0:<60, 1:60–69, 2:70–79, 3:80–89, 4&5:90–100
    buckets = {"90–100%": 0, "80–89%": 0, "70–79%": 0, "60–69%": 0, "< 60%": 0}
    _bucket_map = {0: "< 60%", 1: "60–69%", 2: "70–79%", 3: "80–89%", 4: "90–100%", 5: "90–100%"}
    for b, c in bucket_rows:
        buckets[_bucket_map.get(b, "< 60%")] += c
    health_score_dist = [{"bucket": k, "count": v} for k, v in buckets.items()]

    # 7. Monthly Ticket Volume & Health/Maintenance Trends
    # Ticket counts per month — aggregated in SQL instead of pulling every row.
    _tm_q = db.query(
        extract("month", Ticket.created_at).label("m"),
        func.count(Ticket.id),
    ).filter(Ticket.created_at.isnot(None))
    if warehouse_id:
        _tm_q = _tm_q.filter(Ticket.warehouse_id == warehouse_id)
    ticket_month_rows = _tm_q.group_by("m").all()
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

    # Per-month avg health, from real history — not a fabricated flat line.
    # pdm_batch_predictions can't supply this: it's an upsert table, one row
    # per asset, latest score only. pdm_prediction_history is the append-only
    # log the batch job actually writes on every run — group by real
    # calendar year+month (not bare month-number, which would merge e.g.
    # Jan-2025 and Jan-2026 into one bucket) and anchor the trailing window
    # at the latest real data point rather than "today", so a stale/never-run
    # batch job doesn't produce a trailing run of empty months. Months with
    # no recorded predictions get a null gap rather than an invented number;
    # with no history at all, the array comes back empty so the frontend's
    # "No health-trend data" state shows instead of a misleadingly flat line.
    _health_hist_rows = db.execute(text(f"""
        SELECT to_char(h.predicted_at, 'YYYY-MM') AS ym,
               AVG(h.health_score)                AS avg_health,
               MAX(h.predicted_at)                AS latest
        FROM pdm_prediction_history h
        WHERE h.health_score IS NOT NULL
          AND h.asset_id IN (SELECT id FROM assets {_assets_where})
        GROUP BY ym
    """), _wh).fetchall()

    health_by_ym = {r[0]: float(r[1]) for r in _health_hist_rows}
    if health_by_ym:
        health_anchor_dt = max(r[2] for r in _health_hist_rows)
        health_trends = [
            {
                "month": abbr,
                "avgHealth": round(health_by_ym[f"{y:04d}-{m:02d}"], 1) if f"{y:04d}-{m:02d}" in health_by_ym else None,
                "maintenance": months_dict.get(abbr, 0),
            }
            for (y, m, abbr) in _months_ending_at(health_anchor_dt, 6)
        ]
    else:
        health_trends = []

    # 8. Critical Assets Table — pdm_batch_predictions already holds exactly
    # one (current) row per asset, so no per-asset dedup is needed here.
    # Worst first.
    _crit_where = "AND a.warehouse_id = :wh" if warehouse_id else ""
    critical_assets_query = db.execute(text(f"""
        SELECT a.asset_code, a.model, a.asset_name, a.category, p.health_score
        FROM pdm_batch_predictions p
        JOIN assets a ON a.id = p.asset_id
        WHERE p.status = 'ok' AND p.health_score < 70 {_crit_where}
        ORDER BY p.health_score ASC
        LIMIT 10
    """), _wh).fetchall()

    critical_assets_list = []
    for asset_code, model, asset_name, category, health_score in critical_assets_query:
        hs = float(health_score)
        critical_assets_list.append({
            "id": asset_code or "Unknown",
            "vehicle": model or asset_name or "Vehicle",
            "component": category or "General",
            "health": f"{int(hs)}%",
            "priority": "High" if hs < 50 else "Medium",
            "status": "Critical" if hs < 50 else "Warning"
        })

    # 9. Component Health (from sensor_readings — latest reading per asset)
    component_health = {"avg_tire": 0.0, "avg_brake": 0.0, "avg_battery": 0.0, "avg_oil": 0.0, "avg_hydraulic": 0.0}
    total_fault_codes = 0
    assets_with_sensors = 0
    try:
        comp_row = db.execute(text(f"""
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
                WHERE recorded_at IS NOT NULL AND {_assets_in}
                ORDER BY asset_id, recorded_at DESC
            ) latest
        """), _wh).fetchone()
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
        # Best-effort section — keep the dashboard rendering, but log why the
        # component-health block failed instead of silently swallowing it.
        log.warning("[warehouse] component health query failed", exc_info=True)

    # 10. Recent Maintenance Events (last 10)
    recent_maintenance = []
    try:
        recent_rows = db.execute(text(f"""
            SELECT
                me.id,
                a.asset_name,
                a.asset_code,
                me.event_type,
                me.vendor_name,
                COALESCE(me.cost_amount, 0)::numeric AS cost,
                me.performed_at,
                me.notes
            FROM maintenance_events me
            LEFT JOIN assets a ON me.asset_id = a.id
            WHERE me.performed_at IS NOT NULL
              {"AND a.warehouse_id = :wh" if warehouse_id else ""}
            ORDER BY me.performed_at DESC
            LIMIT 10
        """), _wh).fetchall()
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
        # Best-effort section — log and continue with an empty list.
        log.warning("[warehouse] recent maintenance query failed", exc_info=True)

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
        if warehouse_id:
            wh_row = _s.execute(
                text("SELECT name FROM warehouses WHERE id = :wh"), _wh
            ).fetchone()
        else:
            wh_row = _s.execute(text(
                "SELECT w.name FROM warehouses w "
                "LEFT JOIN assets a ON a.warehouse_id = w.id "
                "GROUP BY w.id, w.name ORDER BY COUNT(a.id) DESC LIMIT 1"
            )).fetchone()
        warehouse_name = wh_row[0] if wh_row and wh_row[0] else "PredictiX"

        avg_age = _s.execute(text(
            f"SELECT ROUND(AVG(vehicle_age_years)::numeric, 1) FROM assets "
            f"WHERE vehicle_age_years IS NOT NULL "
            f"{'AND warehouse_id = :wh' if warehouse_id else ''}"
        ), _wh).scalar()
        active_users = _s.execute(text(
            f"SELECT COUNT(*) FROM profiles WHERE status::text = 'active' "
            f"{'AND warehouse_id = :wh' if warehouse_id else ''}"
        ), _wh).scalar() or 0
        dept_count = _s.execute(text(
            f"SELECT COUNT(*) FROM departments "
            f"{'WHERE warehouse_id = :wh' if warehouse_id else ''}"
        ), _wh).scalar() or 0

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
        log.warning("[warehouse] executive summary build failed", exc_info=True)
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

@warehouse_dashboard_router.get("/departments-overview")
def get_departments_overview(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """Departments in the caller's active warehouse, with active-user counts,
    asset counts, and ticket load per department.

    Scoped the same way as /summary: a regular admin sees their own warehouse's
    departments; a super_admin sees the warehouse they selected at login. If
    there is no active warehouse (e.g. a plain user), all departments are
    returned unscoped.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    warehouse_id = active_warehouse_id(current_user)

    dept_q = db.query(Department)
    if warehouse_id:
        dept_q = dept_q.filter(Department.warehouse_id == warehouse_id)
    departments = dept_q.order_by(Department.name).all()

    if not departments:
        return {"departments": [], "ticketsByDepartment": []}

    dept_ids = [d.id for d in departments]

    # Active users per department (pre-fetched map, no N+1).
    user_counts = dict(
        db.query(Profile.department_id, func.count(Profile.id))
        .filter(Profile.department_id.in_(dept_ids), Profile.status == "active")
        .group_by(Profile.department_id)
        .all()
    )

    # Assets per department (pre-fetched map, no N+1).
    asset_counts = dict(
        db.query(Asset.department_id, func.count(Asset.id))
        .filter(Asset.department_id.in_(dept_ids))
        .group_by(Asset.department_id)
        .all()
    )

    # Ticket load per department — tickets link to a department via their
    # asset, so join Ticket -> Asset and group by Asset.department_id.
    ticket_counts = dict(
        db.query(Asset.department_id, func.count(Ticket.id))
        .join(Ticket, Ticket.asset_id == Asset.id)
        .filter(Asset.department_id.in_(dept_ids))
        .group_by(Asset.department_id)
        .all()
    )
    open_ticket_counts = dict(
        db.query(Asset.department_id, func.count(Ticket.id))
        .join(Ticket, Ticket.asset_id == Asset.id)
        .filter(Asset.department_id.in_(dept_ids), Ticket.status != "closed")
        .group_by(Asset.department_id)
        .all()
    )

    dept_rows = []
    ticket_rows = []
    for d in departments:
        active_users = int(user_counts.get(d.id, 0))
        asset_count = int(asset_counts.get(d.id, 0))
        ticket_count = int(ticket_counts.get(d.id, 0))
        open_tickets = int(open_ticket_counts.get(d.id, 0))

        dept_rows.append({
            "id": str(d.id),
            "name": d.name,
            "code": d.code,
            "activeUsers": active_users,
            "assetCount": asset_count,
            "ticketCount": ticket_count,
            "openTickets": open_tickets,
        })
        ticket_rows.append({"department": d.name, "tickets": ticket_count, "openTickets": open_tickets})

    # Highest ticket load first, so the chart reads as a ranked list.
    ticket_rows.sort(key=lambda r: r["tickets"], reverse=True)

    return {"departments": dept_rows, "ticketsByDepartment": ticket_rows}


@warehouse_dashboard_router.get("/maintenance-schedule")
def get_maintenance_schedule(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    Returns predictive maintenance schedule from real Supabase database data.
    predicted  = PdmBatchPrediction.predicted_days_until_maintenance (ML regressor output)
    scheduled  = last performed_at + fleet avg maintenance interval, projected forward
                 (computed entirely from maintenance_events table — no hardcoded values)
    """
    try:
        warehouse_id = active_warehouse_id(current_user)
        today = datetime.utcnow().date()

        # ── Fleet average maintenance interval from real maintenance history ──
        # Scoped to the warehouse to get a more accurate local interval
        _wh = {"wh": warehouse_id} if warehouse_id else {}
        avg_interval_row = db.execute(text("""
            SELECT AVG(gap_days)::int FROM (
                SELECT
                    EXTRACT(EPOCH FROM (me.performed_at - LAG(me.performed_at)
                        OVER (PARTITION BY me.asset_id ORDER BY me.performed_at))) / 86400 AS gap_days
                FROM maintenance_events me
                JOIN assets a ON me.asset_id = a.id
                WHERE me.performed_at IS NOT NULL
                  AND (a.warehouse_id = :wh OR :wh IS NULL)
            ) sub
            WHERE gap_days > 0 AND gap_days < 365
        """), _wh).scalar()
        avg_interval_days = int(avg_interval_row) if avg_interval_row else 90

        # pdm_batch_predictions already holds exactly one (current) row per
        # asset — no "most recent per asset" subquery/self-join needed here,
        # unlike the old asset_failure_predictions history table this replaced.
        q = (
            db.query(Asset, PdmBatchPrediction)
            .join(PdmBatchPrediction, Asset.id == PdmBatchPrediction.asset_id)
            .filter(
                text("assets.status::text NOT IN ('retired', 'inactive')"),
                PdmBatchPrediction.status == "ok",
                PdmBatchPrediction.predicted_days_until_maintenance.isnot(None),
                PdmBatchPrediction.predicted_days_until_maintenance > 0,
            )
        )
        if warehouse_id:
            q = q.filter(Asset.warehouse_id == warehouse_id)

        rows = q.order_by(PdmBatchPrediction.predicted_days_until_maintenance.asc()).limit(50).all()

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
            predicted_days = round(float(pred.predicted_days_until_maintenance), 1)

            # Scheduled: project from last actual service + fleet avg interval
            scheduled_days = None
            last_svc = last_performed.get(asset.id)
            if last_svc:
                last_date = last_svc.date() if hasattr(last_svc, "date") else last_svc
                from datetime import timedelta as td
                next_proj = last_date + td(days=avg_interval_days)
                days_to_sched = (next_proj - today).days
                scheduled_days = round(max(0, days_to_sched), 1)
            elif asset.last_service_date:
                from datetime import timedelta as td
                next_proj = asset.last_service_date + td(days=avg_interval_days)
                days_to_sched = (next_proj - today).days
                scheduled_days = round(max(0, days_to_sched), 1)

            if scheduled_days is None:
                continue

            schedule.append({
                "asset": asset.asset_name,
                "predicted": predicted_days,
                "scheduled": scheduled_days,
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
def get_survival_analysis(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user),
):
    """
    FRSO Component Survival Analysis (Weibull AFT) for the dashboard.

    Pure model inference over the fleet's lowest-health assets — NO LLM call,
    so it is fast and never rate-limited. Returns per-component RUL summary plus
    a soonest-failing watchlist for live display on the Warehouse page.
    """
    wh_id = active_warehouse_id(current_user)
    try:
        return _survival_cache.get_or_refresh(
            db,
            lambda d: _build_survival_data(d, wh_id),
            key=wh_id,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Survival analysis failed: {str(e)}")


def _build_survival_data(db: Session, warehouse_id: str | None = None):
    # Lowest-health assets (latest prediction per asset, deduped) — the same
    # cohort the PDF report scores, so the page and PDF agree.
    _assets_in = (
        "p.asset_id IN (SELECT id FROM assets WHERE warehouse_id = :wh)"
        if warehouse_id else "TRUE"
    )
    _wh = {"wh": warehouse_id} if warehouse_id else {}
    
    critical_rows = db.execute(text(f"""
        SELECT * FROM (
            SELECT DISTINCT ON (p.asset_id)
                a.asset_code, a.asset_name, a.vehicle_type, p.health_score
            FROM pdm_batch_predictions p
            JOIN assets a ON a.id = p.asset_id
            WHERE {_assets_in}
            ORDER BY p.asset_id, p.predicted_at DESC
        ) latest
        ORDER BY CASE WHEN latest.asset_code LIKE 'SIM-%' THEN 0 ELSE 1 END, latest.health_score ASC
        LIMIT 25
    """), _wh).fetchall()

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
    summary = _build_survival_summary(critical_assets, max_assets=25)

    return {
        "status": "success",
        "survival_summary": summary,
        "critical_assets": critical_assets,
        # ISO-8601 UTC timestamp so the dashboard can show when this was scored.
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


@warehouse_dashboard_router.get("/generate-report")
def generate_warehouse_report(
    db: Session = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    KB-Enhanced Warehouse Report Agent endpoint.
    Aggregates all PostgreSQL data → KB Vector Store retrieval →
    KB Annotations (deterministic) → Llama 3 (via Groq) →
    returns AI sections + raw context + kb_annotations for PDF export.
    Admin access only.
    """
    try:
        from app.agents.report_agents import run_warehouse_agent
        wh_id = active_warehouse_id(current_user)
        result = run_warehouse_agent(db, warehouse_id=wh_id)
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
