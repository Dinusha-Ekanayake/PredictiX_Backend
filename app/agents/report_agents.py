"""
Multi-Agent Warehouse Report System — PredictiX
================================================
Architecture:
  Main Agent (Router)
    ├── Warehouse Report Agent  ← KB-Enhanced RAG + PostgreSQL → Llama 3
   

KB-Enhanced RAG Pipeline:
  1. build_warehouse_context() — queries ALL PostgreSQL tables live
  2. KB Vector Store (TF-IDF) — retrieves relevant KB chunks for query
  3. KB Annotator — deterministic annotations (SHAP thresholds, health bands)
  4. LLM Prompt — PostgreSQL data + KB context injected together
  5. Returns: ai_sections + context + kb_annotations

Data Sources:
  - Live PostgreSQL data (all tables)
  - KB Vector Store (15 documents: ISO 55000, SMRP, OEM intervals)
  - Supabase DB has pgvector extension for future dense embedding upgrade
"""

import os
import json
import re
from typing import Any
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timedelta

from app.models import (
    Asset, AssetFailurePrediction, AssetCostPrediction,
    MaintenanceEvent, Ticket, Profile, Warehouse,
    Department, PredictionFeatureImportance, PredictionExplanation,
)

# ── KB Integration ───────────────────────────────────────────────
from app.kb.kb_vector_store import get_kb_store
from app.kb.kb_annotator import (
    annotate_shap_features,
    annotate_health_bands,
    compute_benchmark_alerts,
    get_ticket_category_kb,
    generate_recommendations,
    get_service_interval_kb_text,
    get_oem_interval_reference,
    get_statutory_compliance_reference,
    rank_fmea_criticality,
    get_climate_risk_flags,
)


# ═══════════════════════════════════════════════════════════════
# LLM SETUP — Groq Llama 3
# ═══════════════════════════════════════════════════════════════

def _get_llm(temperature: float = 0.3) -> ChatGroq:
    """Return ChatGroq (Llama 3.3) — raises RuntimeError if key missing."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set in your .env file. "
            "Get a free key at https://console.groq.com and add: "
            "GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxx"
        )
    return ChatGroq(
        groq_api_key=api_key,
        model_name="llama-3.3-70b-versatile",
        temperature=temperature,
    )


# ═══════════════════════════════════════════════════════════════
# FULL DATA INJECTION — PostgreSQL → LLM Context (RAG Layer)
# ═══════════════════════════════════════════════════════════════

def _build_survival_summary(critical_assets: list, max_assets: int = 12) -> dict | None:
    """FRSO survival aggregation over the report's critical assets.

    Runs the per-component Weibull AFT models on each critical asset and
    aggregates into (a) a per-component RUL summary and (b) a soonest-failing
    watchlist. Returns None on any failure so report generation never blocks.

    Uses its OWN DB session: build_warehouse_context's session may already be in
    an aborted-transaction state from an earlier swallowed query error, which
    would otherwise fail every query here.
    """
    db = None
    try:
        from app.ai.services import survival_service
        from app.db.session import SessionLocal

        db = SessionLocal()
        components = ("brake", "tire", "battery", "oil", "hydraulic")
        codes = [a.get("code") for a in (critical_assets or [])[:max_assets] if a.get("code")]
        if not codes:
            return None

        code_to_id = {
            c: str(i)
            for c, i in db.query(Asset.asset_code, Asset.id).filter(Asset.asset_code.in_(codes)).all()
        }

        comp_rul: dict[str, list] = {c: [] for c in components}
        comp_30 = {c: 0 for c in components}
        comp_90 = {c: 0 for c in components}
        watchlist: list = []
        analyzed = 0

        for a in (critical_assets or [])[:max_assets]:
            aid = code_to_id.get(a.get("code"))
            if not aid:
                continue
            try:
                res = survival_service.predict_all_components(db, aid, horizon_days=180, step_days=14)
            except Exception:
                continue
            analyzed += 1
            for comp in res.get("components", []):
                if "error" in comp:
                    continue
                c = comp["component"]
                md = comp["median_days"]
                comp_rul[c].append(md)
                if md <= 30:
                    comp_30[c] += 1
                if md <= 90:
                    comp_90[c] += 1
            sc, sm = res.get("soonest_component"), res.get("soonest_median_days")
            if sc and sm is not None:
                watchlist.append({
                    "asset": a.get("code"),
                    "component": sc.title(),
                    "rul_days": round(float(sm), 1),
                    "risk": "High" if sm <= 45 else "Medium" if sm <= 90 else "Low",
                })

        if analyzed == 0:
            return None

        component_summary = [
            {
                "component": c.title(),
                "avg_rul_days": round(sum(v) / len(v), 1) if v else None,
                "at_risk_30d": comp_30[c],
                "at_risk_90d": comp_90[c],
                "assets_scored": len(v),
            }
            for c, v in comp_rul.items()
        ]
        watchlist.sort(key=lambda w: w["rul_days"])

        return {
            "assets_analyzed": analyzed,
            "horizon_days": 180,
            "component_summary": component_summary,
            "watchlist": watchlist[:15],
        }
    except Exception:
        return None
    finally:
        if db is not None:
            db.close()


def build_warehouse_context(db: Session) -> dict[str, Any]:
    """
    Queries ALL relevant PostgreSQL tables and builds a comprehensive
    structured context dictionary.

    This is the RAG/data-injection layer:
    - Every key metric is computed from live DB data
    - No mocked or placeholder values
    - Context is later serialised to a structured text block and injected into the LLM
    """

    now = datetime.utcnow()
    three_months_ago = now - timedelta(days=90)
    two_months_ago   = now - timedelta(days=60)
    one_month_ago    = now - timedelta(days=30)

    # ── Warehouse info ────────────────────────────────────
    warehouse = db.query(Warehouse).first()
    warehouse_name = warehouse.name if warehouse else "PredictiX Warehouse"
    warehouse_city = warehouse.city if warehouse else "Colombo"
    warehouse_code = warehouse.code if warehouse else "WH-001"
    warehouse_active = warehouse.is_active if warehouse else True

    # Departments
    dept_count = db.execute(text("SELECT COUNT(*) FROM departments")).scalar() or 0

    # ── ASSETS ────────────────────────────────────────────
    total_assets = db.query(func.count(Asset.id)).scalar() or 0

    asset_status_rows = db.query(Asset.status, func.count(Asset.id)).group_by(Asset.status).all()
    asset_status_breakdown = {
        str(s).replace("_", " ").title() if s else "Unknown": c for s, c in asset_status_rows
    }
    active_assets     = asset_status_breakdown.get("Active", 0)
    inactive_assets   = asset_status_breakdown.get("Inactive", 0)
    under_maintenance = asset_status_breakdown.get("Under Maintenance", 0)
    retired_assets    = asset_status_breakdown.get("Retired", 0)

    asset_type_rows = db.query(Asset.vehicle_type, func.count(Asset.id)).group_by(Asset.vehicle_type).all()
    asset_type_breakdown = {
        str(t).replace("_", " ").title() if t else "Other": c for t, c in asset_type_rows
    }

    asset_category_rows = db.query(Asset.category, func.count(Asset.id)).group_by(Asset.category).all()
    asset_category_breakdown = {
        str(c).replace("_", " ").title() if c else "General": cnt for c, cnt in asset_category_rows
    }

    avg_vehicle_age = db.query(func.avg(Asset.vehicle_age_years)).scalar() or 0

    # ── HEALTH & FAILURE PREDICTIONS ─────────────────────
    # Deduplicate to the LATEST prediction per asset (one row per asset_id) so every
    # health metric is derived from ONE consistent set. Assets accrue multiple
    # prediction runs over time; counting all rows previously over-counted the fleet
    # (health bands summed to more than the asset total).
    latest_preds = db.execute(text("""
        SELECT DISTINCT ON (asset_id)
            asset_id, health_score, failure_probability, risk_level, days_until_maintenance
        FROM asset_failure_predictions
        ORDER BY asset_id, created_at DESC
    """)).fetchall()

    health_vals = [float(r[1]) for r in latest_preds if r[1] is not None]
    scored_assets = len(health_vals)

    avg_health = (sum(health_vals) / scored_assets) if scored_assets else 0
    avg_health_pct = int(avg_health)

    # Canonical health-band counts (single source of truth; see health_buckets below).
    # "Critical" = health < 50 across the ENTIRE report (matches the §1/§7 KPI card).
    # at_risk_count (<60) is retained only to describe the wider danger zone in prose.
    healthy_count  = sum(1 for h in health_vals if h >= 80)
    moderate_count = sum(1 for h in health_vals if 60 <= h < 80)
    at_risk_count  = sum(1 for h in health_vals if h < 60)
    critical_count = sum(1 for h in health_vals if h < 50)

    # Count of assets with no prediction yet (model-coverage gap, surfaced in report).
    unscored_assets = max(int(total_assets) - scored_assets, 0)

    # ── Health-aware status distribution (report display) ──────────────────
    # The raw assets.status column carries its own 'critical' value that differs
    # from the predictive health band (<50%). To keep "Critical" identical to the
    # KPI cards on EVERY page, the report's status distribution uses the health-band
    # Critical (<50%); every non-critical, in-service asset counts as Active. This
    # makes the §2.2 chart, the "Active" counts, and the LLM prompt all consistent
    # with the Critical Assets KPI. (Trade-off: "Active" becomes the in-service,
    # health≥50 remainder rather than the raw status='active' count.)
    display_active = max(
        total_assets - critical_count - under_maintenance - retired_assets - inactive_assets,
        0,
    )
    status_display_breakdown: dict[str, int] = {"Active": display_active, "Critical": critical_count}
    if under_maintenance:
        status_display_breakdown["Under Maintenance"] = under_maintenance
    if retired_assets:
        status_display_breakdown["Retired"] = retired_assets
    if inactive_assets:
        status_display_breakdown["Inactive"] = inactive_assets

    # ML categorical risk_level distribution. Rows with no risk_level are "Unknown",
    # and assets with NO prediction at all are folded into "Unknown" too, so the
    # distribution covers the ENTIRE fleet — every asset lands in exactly one bucket
    # and the "% Fleet" column sums to 100% (denominator = total_assets).
    risk_breakdown: dict[str, int] = {}
    for r in latest_preds:
        label = str(r[3]).title() if r[3] else "Unknown"
        risk_breakdown[label] = risk_breakdown.get(label, 0) + 1
    if unscored_assets:
        risk_breakdown["Unknown"] = risk_breakdown.get("Unknown", 0) + unscored_assets

    fail_probs = [float(r[2]) for r in latest_preds if r[2] is not None]
    raw_prob = (sum(fail_probs) / len(fail_probs)) if fail_probs else 0.0
    # Normalize: if DB stores decimals (0-1), multiply by 100; if already percentage (0-100), use directly
    avg_failure_prob_pct = round(raw_prob * 100 if raw_prob <= 1.0 else raw_prob, 1)
    avg_failure_prob_pct = min(avg_failure_prob_pct, 100.0)  # cap at 100% for display safety

    days_vals = [int(r[4]) for r in latest_preds if r[4] is not None]
    urgent_maintenance = sum(1 for d in days_vals if d <= 7)
    soon_maintenance   = sum(1 for d in days_vals if d <= 30)
    avg_days_to_maintenance = int(sum(days_vals) / len(days_vals)) if days_vals else None

    # SHAP top features from prediction explanations table
    top_explanations_raw = (
        db.query(PredictionFeatureImportance.feature_name, func.count(PredictionFeatureImportance.id))
        .join(PredictionExplanation, PredictionFeatureImportance.explanation_id == PredictionExplanation.id)
        .filter(PredictionFeatureImportance.rank_order <= 3)
        .group_by(PredictionFeatureImportance.feature_name)
        .order_by(func.count(PredictionFeatureImportance.id).desc())
        .limit(8)
        .all()
    )
    top_shap_features = [(name, count) for name, count in top_explanations_raw]

    # Fallback: pull from top_explanations JSONB on asset_failure_predictions
    if not top_shap_features:
        critical_preds = db.query(AssetFailurePrediction).filter(
            AssetFailurePrediction.health_score < 60
        ).limit(20).all()
        feat_counts: dict[str, int] = {}
        for pred in critical_preds:
            explanations = pred.top_explanations or {}
            for feat in (explanations.get("features") or [])[:3]:
                name = feat.get("feature", "unknown")
                feat_counts[name] = feat_counts.get(name, 0) + 1
        top_shap_features = sorted(feat_counts.items(), key=lambda x: -x[1])[:8]

    # Health score distribution buckets — derived from the SAME deduped per-asset set,
    # so the bands always sum to scored_assets. "Below 60%" is split into "50–59%"
    # (high-risk) and "Below 50%" (canonical Critical = the §1/§7 KPI count).
    health_buckets = {"90-100%": 0, "80-89%": 0, "70-79%": 0, "60-69%": 0, "50-59%": 0, "Below 50%": 0}
    for score in health_vals:
        if score >= 90:   health_buckets["90-100%"] += 1
        elif score >= 80: health_buckets["80-89%"] += 1
        elif score >= 70: health_buckets["70-79%"] += 1
        elif score >= 60: health_buckets["60-69%"] += 1
        elif score >= 50: health_buckets["50-59%"] += 1
        else:             health_buckets["Below 50%"] += 1

    # Worst assets by LATEST health score (deduped per asset). A watch list of the
    # lowest-health units (<60), not the Critical count — so an asset cannot appear
    # twice from multiple prediction runs.
    critical_rows = db.execute(text("""
        SELECT * FROM (
            SELECT DISTINCT ON (p.asset_id)
                a.asset_code, a.asset_name, a.model, a.make, a.vehicle_type, a.status,
                p.health_score, p.failure_probability, p.risk_level, p.days_until_maintenance
            FROM asset_failure_predictions p
            JOIN assets a ON a.id = p.asset_id
            ORDER BY p.asset_id, p.created_at DESC
        ) latest
        WHERE latest.health_score < 60
        ORDER BY latest.health_score ASC
        LIMIT 8
    """)).fetchall()
    def _fp_pct(v) -> str:
        fp = float(v or 0)
        return f"{min(round(fp * 100 if fp <= 1.0 else fp, 1), 100.0)}%"
    critical_assets_list = [
        {
            "code": r[0],
            "name": r[1] or r[2] or "Vehicle",
            "type": str(r[4]).replace("_", " ").title() if r[4] else "Unknown",
            "make": r[3] or "N/A",
            "model": r[2] or "N/A",
            "health_score": int(r[6]),
            "health": f"{int(r[6])}%",
            "failure_prob": _fp_pct(r[7]),
            "risk": r[8] or "High",
            "days_to_service": r[9],
            "status": r[5] or "unknown",
        }
        for r in critical_rows
    ]

    # ── COST PREDICTIONS ──────────────────────────────────
    total_estimated_cost = db.query(func.sum(AssetCostPrediction.estimated_cost)).scalar() or 0
    avg_cost_per_asset   = db.query(func.avg(AssetCostPrediction.estimated_cost)).scalar() or 0
    min_cost_estimate    = db.query(func.min(AssetCostPrediction.min_cost)).scalar() or 0
    max_cost_estimate    = db.query(func.max(AssetCostPrediction.max_cost)).scalar() or 0
    cost_currency        = db.query(AssetCostPrediction.currency).first()
    currency             = cost_currency[0] if cost_currency else "LKR"

    # ── MAINTENANCE EVENTS ────────────────────────────────
    # Reporting window = the THREE CALENDAR MONTHS ending with the most RECENT activity
    # (latest maintenance event / ticket), falling back to "now" when there is none.
    # Anchoring to the data — not the wall clock — keeps the report populated even when
    # the dataset is seed/demo data timestamped in the past: a fixed "last 3 months from
    # today" window slides off old data and shows all zeros. In production the latest
    # activity ≈ today, so this behaves exactly like "last 3 months".
    # The monthly trend buckets AND the 3-month headline totals are derived from this
    # SAME window (totals = sum of the buckets), so they can never disagree.
    def _month_floor(d: datetime) -> datetime:
        return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    def _next_month(d: datetime) -> datetime:
        return _month_floor(_month_floor(d) + timedelta(days=32))

    _latest_evt = db.query(func.max(MaintenanceEvent.performed_at)).scalar()
    _latest_tkt = db.query(func.max(Ticket.created_at)).scalar()
    _anchors = [d for d in (_latest_evt, _latest_tkt) if d is not None]
    # Strip tzinfo so the anchor matches the naive `now` used elsewhere.
    anchor = max(_anchors).replace(tzinfo=None) if _anchors else now
    window_is_current = (_month_floor(anchor) == _month_floor(now))

    month_starts: list[datetime] = []
    _m = _month_floor(anchor)
    for _ in range(3):
        month_starts.append(_m)
        _m = _month_floor(_m - timedelta(days=1))   # robust step to previous month
    month_starts.reverse()                           # oldest → newest
    period_start = month_starts[0]
    period_end   = _next_month(month_starts[-1])

    # Monthly maintenance volume + cost over the 3 calendar months
    monthly_maintenance = []
    for ms in month_starts:
        me = _next_month(ms)
        m_cost = db.query(func.sum(MaintenanceEvent.cost_amount)).filter(
            MaintenanceEvent.performed_at >= ms,
            MaintenanceEvent.performed_at <  me,
        ).scalar() or 0
        m_count = db.query(func.count(MaintenanceEvent.id)).filter(
            MaintenanceEvent.performed_at >= ms,
            MaintenanceEvent.performed_at <  me,
        ).scalar() or 0
        monthly_maintenance.append({
            "month": ms.strftime("%B %Y"),
            "cost": int(m_cost),
            "events": m_count,
        })

    # Headline totals are the SUM of the displayed months → trend & headline reconcile.
    total_maintenance_3m = sum(m["events"] for m in monthly_maintenance)
    actual_cost_3m       = sum(m["cost"]   for m in monthly_maintenance)

    avg_downtime = db.query(func.avg(MaintenanceEvent.downtime_hours)).filter(
        MaintenanceEvent.performed_at >= period_start,
        MaintenanceEvent.performed_at <  period_end,
    ).scalar() or 0

    maintenance_type_rows = db.query(
        MaintenanceEvent.event_type, func.count(MaintenanceEvent.id)
    ).filter(
        MaintenanceEvent.performed_at >= period_start,
        MaintenanceEvent.performed_at <  period_end,
    ).group_by(MaintenanceEvent.event_type).all()
    maintenance_type_breakdown = {
        str(t).replace("_", " ").title() if t else "General": c for t, c in maintenance_type_rows
    }

    # Canonical PM ratio = preventive events / all events (clamped ≤100%). Single
    # source so prose, KPI cards and benchmark box never disagree on the figure.
    _mtb_lower = {str(k).lower(): v for k, v in maintenance_type_breakdown.items()}
    _preventive_events = _mtb_lower.get("preventive", 0) + _mtb_lower.get("scheduled", 0)
    _total_events_typed = sum(maintenance_type_breakdown.values())
    pm_ratio_pct = round(min(_preventive_events / _total_events_typed * 100, 100.0), 1) if _total_events_typed else 0.0

    # Seed/demo-data signature: is the history concentrated in a single month? If one
    # month holds ≥80% of events, the "trend" is a data-loading artifact, not an
    # operational decline — flagged honestly in the report so it isn't read as insight.
    _evts  = [m["events"] for m in monthly_maintenance]
    _costs = [m["cost"]   for m in monthly_maintenance]
    maintenance_data_concentrated = bool(
        total_maintenance_3m > 0 and max(_evts) / total_maintenance_3m >= 0.8
    )
    maintenance_trend_direction = (
        "increasing" if _evts[-1] > _evts[0] else "decreasing" if _evts[-1] < _evts[0] else "stable"
    )
    cost_trend_direction = (
        "increasing" if _costs[-1] > _costs[0] else "decreasing" if _costs[-1] < _costs[0] else "stable"
    )

    # ── TICKETS ───────────────────────────────────────────
    total_tickets    = db.query(func.count(Ticket.id)).scalar() or 0
    open_tickets     = db.execute(text("SELECT COUNT(*) FROM tickets WHERE status = 'open'")).scalar() or 0
    in_progress      = db.execute(text("SELECT COUNT(*) FROM tickets WHERE status = 'in_progress'")).scalar() or 0
    resolved_tickets = db.execute(text("SELECT COUNT(*) FROM tickets WHERE status = 'resolved'")).scalar() or 0
    closed_tickets   = db.execute(text("SELECT COUNT(*) FROM tickets WHERE status = 'closed'")).scalar() or 0
    active_tickets   = open_tickets + in_progress

    priority_rows = db.query(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).all()
    priority_breakdown = {str(p).title() if p else "Unset": c for p, c in priority_rows}

    final_priority_rows = db.query(Ticket.final_priority, func.count(Ticket.id)).group_by(Ticket.final_priority).all()
    final_priority_breakdown = {str(p).title() if p else "Unset": c for p, c in final_priority_rows}

    category_rows = db.query(Ticket.final_category, func.count(Ticket.id)).group_by(Ticket.final_category).all()
    category_breakdown = {str(c).title() if c else "General": cnt for c, cnt in category_rows}

    # Monthly ticket volumes over the SAME 3 calendar months as the maintenance trend.
    ticket_trend = []
    for ms in month_starts:
        me = _next_month(ms)
        count = db.query(func.count(Ticket.id)).filter(
            Ticket.created_at >= ms,
            Ticket.created_at < me,
        ).scalar() or 0
        ticket_trend.append({"month": ms.strftime("%B %Y"), "tickets": count})

    # High priority active tickets
    high_priority_active = db.execute(
        text("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('closed','resolved') AND (priority = 'high' OR final_priority = 'high')")
    ).scalar() or 0

    # ── USERS ─────────────────────────────────────────────
    total_users    = db.query(func.count(Profile.id)).scalar() or 0
    active_users   = db.execute(text("SELECT COUNT(*) FROM profiles WHERE status = 'active'")).scalar() or 0
    inactive_users = total_users - active_users
    admin_users    = db.execute(text("SELECT COUNT(*) FROM profiles WHERE role = 'admin'")).scalar() or 0
    standard_users = total_users - admin_users

    # ── MONTHLY TREND SUMMARY (3m) ───────────────────────
    # Compare current month vs 2 months ago
    current_month_tickets = ticket_trend[-1]["tickets"] if ticket_trend else 0
    oldest_month_tickets  = ticket_trend[0]["tickets"]  if ticket_trend else 0
    ticket_trend_direction = "increasing" if current_month_tickets > oldest_month_tickets else (
        "decreasing" if current_month_tickets < oldest_month_tickets else "stable"
    )

    # ── PHASE B: EXTENDED DB QUERIES ─────────────────────

    # B1. Fleet Age Distribution (from assets.manufacture_year)
    current_year = now.year
    fleet_age_distribution = {"0-3 yrs": 0, "4-6 yrs": 0, "7-10 yrs": 0, "10+ yrs": 0}
    try:
        age_rows = db.query(Asset.manufacture_year, func.count(Asset.id))\
            .filter(Asset.manufacture_year.isnot(None)).group_by(Asset.manufacture_year).all()
        for yr, cnt in age_rows:
            age = current_year - int(yr)
            band = "0-3 yrs" if age <= 3 else "4-6 yrs" if age <= 6 else "7-10 yrs" if age <= 10 else "10+ yrs"
            fleet_age_distribution[band] += cnt
    except Exception:
        pass

    # Surface assets with no manufacture_year as an explicit "Unknown" band so the
    # age bands reconcile to the full fleet (total_assets). Without this they
    # silently sum to fewer than total_assets and the per-band percentages are
    # computed on the wrong base.
    known_age_count = sum(fleet_age_distribution.values())
    unknown_age_count = max(total_assets - known_age_count, 0)
    if unknown_age_count:
        fleet_age_distribution["Unknown"] = unknown_age_count

    # B2. Warranty Expiry Alert (assets expiring within 90 days)
    warranty_expiring_90d = 0
    try:
        expiry_cutoff = (now + timedelta(days=90)).date()
        today_date = now.date()
        warranty_expiring_90d = db.execute(text("""
            SELECT COUNT(*) FROM assets
            WHERE warranty_expiry_date IS NOT NULL
              AND warranty_expiry_date >= :today
              AND warranty_expiry_date <= :cutoff
        """), {"today": today_date, "cutoff": expiry_cutoff}).scalar() or 0
    except Exception:
        pass

    # B3. Component Health Averages (sensor_readings — latest per asset)
    component_health: dict[str, float] = {
        "avg_tire": 0.0, "avg_brake": 0.0, "avg_battery": 0.0,
        "avg_oil": 0.0, "avg_hydraulic": 0.0,
    }
    total_fault_codes = 0
    avg_fault_codes_per_asset = 0.0
    monitored_assets = 0
    try:
        comp_row = db.execute(text("""
            SELECT
                ROUND(AVG(tire_health_pct)::numeric, 1)        AS avg_tire,
                ROUND(AVG(brake_health_pct)::numeric, 1)       AS avg_brake,
                ROUND(AVG(battery_health_pct)::numeric, 1)     AS avg_battery,
                ROUND(AVG(oil_life_pct)::numeric, 1)           AS avg_oil,
                ROUND(AVG(hydraulic_health_pct)::numeric, 1)   AS avg_hydraulic,
                COALESCE(SUM(active_fault_code_count), 0)::int  AS total_faults,
                ROUND(AVG(active_fault_code_count)::numeric, 2) AS avg_faults,
                COUNT(*)::int                                  AS monitored_assets
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
                "avg_tire":     float(comp_row[0] or 0),
                "avg_brake":    float(comp_row[1] or 0),
                "avg_battery":  float(comp_row[2] or 0),
                "avg_oil":      float(comp_row[3] or 0),
                "avg_hydraulic":float(comp_row[4] or 0),
            }
            total_fault_codes          = int(comp_row[5] or 0)
            avg_fault_codes_per_asset  = float(comp_row[6] or 0)
            monitored_assets           = int(comp_row[7] or 0)
    except Exception:
        pass

    # B4. Vendor & Service Provider Breakdown (maintenance_events)
    vendor_breakdown: list[dict] = []
    try:
        vendor_rows = db.execute(text("""
            SELECT vendor_name,
                   COUNT(*)::int                            AS event_count,
                   COALESCE(SUM(cost_amount), 0)::numeric  AS total_cost
            FROM maintenance_events
            WHERE vendor_name IS NOT NULL AND vendor_name <> ''
              AND performed_at >= :cutoff
            GROUP BY vendor_name
            ORDER BY event_count DESC
            LIMIT 6
        """), {"cutoff": three_months_ago}).fetchall()
        vendor_breakdown = [
            {"vendor": r[0], "events": int(r[1]), "cost": float(r[2])}
            for r in vendor_rows
        ]
    except Exception:
        pass

    # B5. Ticket MTTR — Mean Time to Resolve
    avg_resolution_hours = 0.0
    avg_resolution_days  = 0.0
    mttr_by_priority: list[dict] = []
    try:
        mttr_row = db.execute(text("""
            SELECT
                ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - opened_at)) / 3600)::numeric,  1) AS avg_hours,
                ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - opened_at)) / 86400)::numeric, 1) AS avg_days
            FROM tickets
            WHERE resolved_at IS NOT NULL AND opened_at IS NOT NULL
        """)).fetchone()
        if mttr_row:
            avg_resolution_hours = float(mttr_row[0] or 0)
            avg_resolution_days  = float(mttr_row[1] or 0)

        prio_rows = db.execute(text("""
            SELECT COALESCE(final_priority, priority, 'Unknown') AS priority,
                   ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - opened_at)) / 3600)::numeric, 1) AS avg_hours
            FROM tickets
            WHERE resolved_at IS NOT NULL AND opened_at IS NOT NULL
            GROUP BY COALESCE(final_priority, priority, 'Unknown')
            ORDER BY avg_hours DESC
        """)).fetchall()
        mttr_by_priority = [
            {"priority": str(r[0]).title(), "avg_hours": float(r[1] or 0)}
            for r in prio_rows
        ]
    except Exception:
        pass

    return {
        # Warehouse
        "warehouse_name": warehouse_name,
        "warehouse_city": warehouse_city,
        "warehouse_code": warehouse_code,
        "warehouse_active": warehouse_active,
        "department_count": dept_count,
        "report_date": now.strftime("%B %d, %Y"),
        "period": f"{month_starts[0].strftime('%b')}–{month_starts[-1].strftime('%b %Y')}",
        "reporting_window_current": window_is_current,

        # Assets
        "total_assets": total_assets,
        "active_assets": display_active,            # in-service, health≥50 remainder (see health-aware status above)
        "inactive_assets": inactive_assets,
        "under_maintenance_assets": under_maintenance,
        "retired_assets": retired_assets,
        "asset_type_breakdown": asset_type_breakdown,
        "asset_status_breakdown": status_display_breakdown,  # health-band Critical (<50%) for cross-page consistency
        "asset_category_breakdown": asset_category_breakdown,
        "avg_vehicle_age_years": round(float(avg_vehicle_age), 1),

        # Health
        "avg_health_pct": avg_health_pct,
        "healthy_count": healthy_count,
        "moderate_count": moderate_count,
        "at_risk_count": at_risk_count,
        "critical_count": critical_count,
        # Canonical, pre-computed rates so prose never re-derives (or mis-derives) them.
        "critical_rate_pct": round(critical_count / max(total_assets, 1) * 100, 1),
        "at_risk_rate_pct": round(at_risk_count / max(total_assets, 1) * 100, 1),
        "scored_assets": scored_assets,
        "unscored_assets": unscored_assets,
        "avg_failure_prob_pct": avg_failure_prob_pct,
        "risk_breakdown": risk_breakdown,
        "health_score_distribution": health_buckets,
        "top_shap_features": top_shap_features,
        "urgent_maintenance_count": urgent_maintenance,
        "soon_maintenance_count": soon_maintenance,
        "avg_days_to_maintenance": avg_days_to_maintenance,
        "critical_assets": critical_assets_list,
        # FRSO survival analysis (Weibull AFT) aggregated over critical assets
        "survival_summary": _build_survival_summary(critical_assets_list),

        # Cost
        "total_estimated_cost": int(total_estimated_cost),
        "avg_cost_per_asset": int(avg_cost_per_asset),
        "min_cost_estimate": int(min_cost_estimate),
        "max_cost_estimate": int(max_cost_estimate),
        "currency": currency,

        # Maintenance
        "total_maintenance_events_3m": total_maintenance_3m,
        "actual_cost_3m": int(actual_cost_3m),
        "avg_downtime_hours": round(float(avg_downtime), 1),
        "maintenance_type_breakdown": maintenance_type_breakdown,
        "pm_ratio_pct": pm_ratio_pct,
        "monthly_maintenance_trend": monthly_maintenance,
        "maintenance_trend_direction": maintenance_trend_direction,
        "cost_trend_direction": cost_trend_direction,
        "maintenance_data_concentrated": maintenance_data_concentrated,

        # Tickets
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "in_progress_tickets": in_progress,
        "active_tickets": active_tickets,
        "resolved_tickets": resolved_tickets,
        "closed_tickets": closed_tickets,
        "high_priority_active_tickets": high_priority_active,
        "ticket_priority_breakdown": priority_breakdown,
        "ticket_final_priority_breakdown": final_priority_breakdown,
        "ticket_category_breakdown": category_breakdown,
        "ticket_trend_last_3m": ticket_trend,
        "ticket_trend_direction": ticket_trend_direction,

        # Users
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "admin_users": admin_users,
        "standard_users": standard_users,

        # Phase B — Extended DB fields
        "fleet_age_distribution": fleet_age_distribution,
        "warranty_expiring_90d": int(warranty_expiring_90d),
        "component_health": component_health,
        "total_fault_codes": total_fault_codes,
        "avg_fault_codes_per_asset": avg_fault_codes_per_asset,
        "monitored_assets": monitored_assets,   # assets with sensor readings (base for component/fault averages)
        "vendor_breakdown": vendor_breakdown,
        "avg_resolution_hours": avg_resolution_hours,
        "avg_resolution_days": avg_resolution_days,
        "mttr_by_priority": mttr_by_priority,
    }


def _context_to_prompt_text(ctx: dict) -> str:
    """
    Serialises the context dict into a rich structured plain-text block
    suitable for LLM injection (RAG grounding).
    """
    def kv(d: dict) -> str:
        return ", ".join(f"{k}: {v}" for k, v in d.items()) if d else "N/A"

    critical_text = "\n".join(
        f"  • {a['code']} | {a['name']} ({a['type']}) | "
        f"Health: {a['health']} | Failure Prob: {a['failure_prob']} | "
        f"Risk: {a['risk']} | Days to Service: {a['days_to_service'] or 'N/A'}"
        for a in ctx.get("critical_assets", [])
    ) or "  None"

    shap_text = ", ".join(
        f"{feat} (cited {cnt} times)" for feat, cnt in ctx.get("top_shap_features", [])
    ) or "No SHAP explanation data"

    m_trend = " → ".join(
        f"{m['month']}: {m['events']} events / {ctx['currency']} {m['cost']:,}"
        for m in ctx.get("monthly_maintenance_trend", [])
    )
    t_trend = " → ".join(
        f"{t['month']}: {t['tickets']} tickets"
        for t in ctx.get("ticket_trend_last_3m", [])
    )

    return f"""
╔══════════════════════════════════════════════════════════════╗
  PREDICTIХ WAREHOUSE INTELLIGENCE REPORT — {ctx['report_date']}
  Reporting Period: {ctx['period']}
╚══════════════════════════════════════════════════════════════╝

▶ WAREHOUSE
  Name: {ctx['warehouse_name']} ({ctx['warehouse_code']}) | City: {ctx['warehouse_city']}
  Status: {"Active" if ctx.get("warehouse_active") else "Inactive"} | Departments: {ctx.get("department_count", "N/A")}

▶ FLEET ASSETS (Total: {ctx['total_assets']})
  Active: {ctx['active_assets']} | Inactive: {ctx['inactive_assets']} | Under Maintenance: {ctx['under_maintenance_assets']} | Retired: {ctx['retired_assets']}
  Average Vehicle Age: {ctx['avg_vehicle_age_years']} years
  By Type: {kv(ctx['asset_type_breakdown'])}
  By Status: {kv(ctx['asset_status_breakdown'])}

▶ HEALTH & PREDICTIVE ANALYTICS
  Average Fleet Health Score: {ctx['avg_health_pct']}%
  Average Failure Probability: {ctx['avg_failure_prob_pct']}%
  Health Distribution: Healthy (≥80%): {ctx['healthy_count']} | Moderate (60-79%): {ctx['moderate_count']} | At-Risk (<60%): {ctx['at_risk_count']} | Critical (<50%): {ctx['critical_count']}
  Critical Rate: {ctx['critical_rate_pct']}% ({ctx['critical_count']} of {ctx['total_assets']} assets, <50% health) | At-Risk Rate: {ctx['at_risk_rate_pct']}% (<60% health)
  (Use these EXACT pre-computed rates when stating critical/at-risk percentages — do not recompute.)
  Risk Level Distribution: {kv(ctx['risk_breakdown'])}
  Assets Needing Urgent Service (≤7 days): {ctx['urgent_maintenance_count']}
  Assets Needing Service Soon (≤30 days): {ctx['soon_maintenance_count']}
  Average Days Until Next Service: {ctx['avg_days_to_maintenance'] or 'N/A'}

  Top AI-Identified Failure Drivers (SHAP):
  {shap_text}

▶ CRITICAL ASSETS (Lowest Health Scores):
{critical_text}

▶ COST FORECAST ({ctx['currency']})
  Total Predicted Maintenance Cost: {ctx['currency']} {ctx['total_estimated_cost']:,}
  Average Cost Per Asset: {ctx['currency']} {ctx['avg_cost_per_asset']:,}
  Cost Range: {ctx['currency']} {ctx['min_cost_estimate']:,} – {ctx['currency']} {ctx['max_cost_estimate']:,}
  Actual Maintenance Spend (Last 3 Months): {ctx['currency']} {ctx['actual_cost_3m']:,}

▶ MAINTENANCE EVENTS ({ctx['period']})
  Total Events: {ctx['total_maintenance_events_3m']} (this EQUALS the sum of the Monthly Trend below)
  Average Downtime per Event: {ctx['avg_downtime_hours']} hours
  By Type: {kv(ctx['maintenance_type_breakdown'])}
  PM Ratio: {ctx['pm_ratio_pct']}% (preventive share of all events — use this EXACT value; do not recompute)
  Monthly MAINTENANCE-EVENT Trend (events & {ctx['currency']} cost): {m_trend}
  Maintenance event-volume direction: {ctx.get('maintenance_trend_direction', 'n/a')}; maintenance-cost direction: {ctx.get('cost_trend_direction', 'n/a')}
  {"DATA NOTE: maintenance history is concentrated in a single month (demonstration/seed data). Treat the month-over-month change as a DATA-LOADING ARTIFACT, NOT an operational improvement; do not attribute the decline to efficiency." if ctx.get('maintenance_data_concentrated') else ""}

▶ TICKETS
  Total: {ctx['total_tickets']} | Active (Open+InProgress): {ctx['active_tickets']} | Open: {ctx['open_tickets']} | In Progress: {ctx['in_progress_tickets']} | Resolved: {ctx['resolved_tickets']} | Closed: {ctx['closed_tickets']}
  High-Priority Active Tickets: {ctx['high_priority_active_tickets']}
  Priority Breakdown: {kv(ctx['ticket_priority_breakdown'])}
  Category Breakdown: {kv(ctx['ticket_category_breakdown'])}
  Monthly TICKET Trend (count of NEW tickets — a SEPARATE series from maintenance events above; never merge the two): {t_trend} [direction: {ctx['ticket_trend_direction']}]

▶ WORKFORCE / USERS
  Total Users: {ctx['total_users']} | Active: {ctx['active_users']} | Inactive: {ctx['inactive_users']}
  Admin Users: {ctx['admin_users']} | Standard Users: {ctx['standard_users']}
""".strip()


# ═══════════════════════════════════════════════════════════════
# WAREHOUSE REPORT AGENT
# ═══════════════════════════════════════════════════════════════

WAREHOUSE_SYSTEM_PROMPT = """
You are a senior AI warehouse operations analyst for PredictiX, a KB-Enhanced AI-powered fleet management system.
You will receive:
  (A) LIVE PostgreSQL data — all metrics computed from the actual database
  (B) KNOWLEDGE BASE context — maintenance knowledge spanning ISO 55000/55001 and SMRP standards,
      the Sri Lanka Factories Ordinance No. 45 of 1942 (statutory lifting-equipment inspection intervals),
      OEM service schedules (Toyota forklifts, Tata heavy trucks), FMEA/FMECA criticality methodology,
      and the Colombo climate-vulnerability profile relevant to the warehouse.

Generate a professional warehouse intelligence report grounded in BOTH the data AND the KB standards.

Respond with ONLY a valid JSON object with EXACTLY these 5 keys:
{
  "insight_summary": "...",
  "risk_analysis": "...",
  "maintenance_intelligence": "...",
  "pattern_and_trend": "...",
  "conclusion": "..."
}

Section instructions (each must be 4-6 sentences, professional analytical tone):

1. insight_summary:
   Write an executive overview covering: total fleet size and composition (mention specific asset types),
   average health score, active vs critical assets, estimated maintenance cost, active tickets,
   active users, and general warehouse status. When stating the critical rate, use the provided
   "Critical Rate" value verbatim and compare it to the KB benchmark (ISO 55000 5% critical target)
   if it exceeds it. Mention specific numbers from the data.

2. risk_analysis:
   Analyse the risk landscape using the KB context. State the critical/at-risk counts and use the provided
   "Critical Rate" / "At-Risk Rate" values verbatim (do not recompute), comparing to the ISO 55000 / SMRP 5% benchmark. Name the top AI-identified SHAP failure drivers
   and their KB-defined thresholds. Apply FMEA/FMECA criticality reasoning where the data warrants — a
   high-occurrence SHAP driver on a high-severity component (brakes, hydraulics, cooling) is a top-criticality
   item to ground first. Identify which asset types are most critical. Where the Colombo climate profile is
   relevant (heat/humidity raising coolant, battery or corrosion risk), note it. Comment on failure probability
   and urgency — reference assets needing service within 7 days.

3. maintenance_intelligence:
   Outline the maintenance workload using KB standards. How many assets need urgent attention (≤7 days)?
   Compare the provided "PM Ratio" value (use it verbatim; do not recompute) against the SMRP 90% gold standard.
   When comparing predicted cost vs actual 3M spend, describe the gap factually (forecast conservatism or
   deferred maintenance are possible causes) — do not assert it as "savings" or "underspend" without basis.
   Describe maintenance event breakdown and note average downtime. Reference KB service interval standards
   for the most common asset types, citing OEM schedules where relevant (Toyota forklifts every 500 engine
   hours with 8h/40h/170h tiers; Tata heavy trucks ~1000 hours or annually; vans every 60 days). Where lifting
   equipment is involved, note the statutory Factories Ordinance obligation (hoists/lifts examined every 12
   months, lifting tackle every 6 months) as a binding floor independent of OEM intervals.

4. pattern_and_trend:
   Describe observable trends over the reporting period. Treat MAINTENANCE EVENTS and TICKETS as TWO SEPARATE
   series — never state a ticket count as an event count or vice-versa, and never merge their trends.
   State the ticket-volume direction and the maintenance event-volume and maintenance-cost directions using the
   EXACT direction labels provided in the data (do not infer the opposite of what the data says).
   CRITICAL: if the data carries a "DATA NOTE" that the maintenance history is concentrated in one month, you MUST
   describe the month-over-month change as a data-loading artifact of demonstration data and explicitly NOT
   attribute it to operational efficiency or genuine workload reduction. Note patterns in ticket categories
   (electrical/mechanical/general) and their link to SHAP failure drivers.

5. conclusion:
   Write a comprehensive 3-month warehouse summary. Note the PM ratio strength (use the provided "PM Ratio"
   value verbatim) and fleet health trajectory. When referring to "critical" assets, use the provided
   Critical (<50% health) count and Critical Rate verbatim — do not introduce a different figure.
   Reference the split operational profile (strong PM culture vs high critical asset rate).
   If you mention the estimated-vs-actual cost difference, describe it neutrally as a forecast-vs-actual
   variance (possible causes: cost-model conservatism OR deferred maintenance) — do NOT label it "underspend"
   or "savings", and do not recommend budget cuts on the basis of the gap alone.
   Frame management actions within the three-layer compliance model (statutory Factories Ordinance →
   OEM intervals → ISO 55000/55001 + SMRP predictive standards), noting that the strictest applicable trigger
   binds. Provide the top 3 recommended actions grounded in KB thresholds, with specific numbers, and reflect
   ISO 55001 whole-lifecycle-cost thinking in the financial position and ticket resolution performance.

STRICT RULES:
- Use ONLY numbers from the provided data context. Never invent or estimate.
- Do NOT compute, derive, or estimate any percentage, ratio, or delta yourself. Only state a
  percentage/ratio if it is explicitly present in the data context. If one is not provided, describe
  the underlying counts instead (e.g. "318 of 1,156 assets" rather than an invented percentage).
- "Critical" assets means the Critical band (<50% health) count ONLY. Do NOT merge it with the
  At-Risk (<60% health) count or report a blended figure — they are distinct numbers.
- A ratio of a part to a whole can never exceed 100%. Never state a coverage/ratio above 100%.
- Reference KB standards (ISO 55000, SMRP) naturally when the data warrants it.
- Do NOT include markdown, backticks, bullet points, or extra text outside the JSON.
- Each section must be a single flowing paragraph (no sub-headings inside values).
- KB context is grounding information — cite it when making threshold-based observations.
"""


_TREND_UP   = r"(rising|increas|upward|climb|grew|grow|higher|trend\w*\s+up)"
_TREND_DOWN = r"(falling|decreas|declin|downward|drop|lower|reduc|trend\w*\s+down)"


def _guard_narrative(ai_sections: dict, ctx: dict) -> dict:
    """
    Deterministic faithfulness guard over the generated narrative.

    1. Appends an AUTHORITATIVE, data-grounded trend sentence (true directions for
       maintenance events, maintenance cost and tickets) so the reader always has
       ground truth even if the prose drifts.
    2. Detects a cost-direction contradiction in the prose (claims cost up while the
       data falls, or vice-versa) and prefixes the note with "Correction —".
    3. If the maintenance history is concentrated in one month (demo/seed data),
       states that the month-over-month change is an artifact and must NOT be read
       as efficiency.
    """
    evt_dir  = ctx.get("maintenance_trend_direction", "n/a")
    cost_dir = ctx.get("cost_trend_direction", "n/a")
    tkt_dir  = ctx.get("ticket_trend_direction", "n/a")
    concentrated = bool(ctx.get("maintenance_data_concentrated"))
    period = ctx.get("period", "the period")

    pat = (ai_sections.get("pattern_and_trend") or "").strip()
    scan = (pat + " " + (ai_sections.get("conclusion") or "")).lower()

    # Bind the direction word to "cost" (within a short window) so an unrelated
    # "decreasing ticket volume" elsewhere doesn't mask a wrong cost claim.
    contradiction = False
    if "cost" in scan and cost_dir in ("increasing", "decreasing"):
        cost_up = (re.search(r"cost\w*[^.]{0,40}" + _TREND_UP, scan) is not None
                   or re.search(_TREND_UP + r"[^.]{0,25}cost", scan) is not None)
        cost_down = (re.search(r"cost\w*[^.]{0,40}" + _TREND_DOWN, scan) is not None
                     or re.search(_TREND_DOWN + r"[^.]{0,25}cost", scan) is not None)
        if cost_dir == "decreasing" and cost_up and not cost_down:
            contradiction = True
        elif cost_dir == "increasing" and cost_down and not cost_up:
            contradiction = True

    note = (
        f"Data-grounded trend ({period}): maintenance event volume is {evt_dir}, maintenance cost is "
        f"{cost_dir}, and support-ticket volume is {tkt_dir}. Maintenance events and tickets are separate "
        f"series and must not be used interchangeably."
    )
    if concentrated:
        note += (
            " The maintenance history is concentrated in a single month (demonstration data), so these "
            "month-over-month changes are a data-loading artifact and do not indicate improved operational efficiency."
        )
    if contradiction:
        note = "Correction — " + note

    sep = "" if (not pat or pat.endswith((" ", "\n"))) else " "
    ai_sections["pattern_and_trend"] = (pat + sep + note).strip()
    return ai_sections


def run_warehouse_agent(db: Session) -> dict:
    """
    KB-Enhanced Warehouse Report Agent:
    1. Queries ALL PostgreSQL tables → builds context (build_warehouse_context)
    2. KB Vector Store retrieval → top KB chunks for each report section
    3. KB Annotator → deterministic SHAP, health band, benchmark, ticket annotations
    4. LLM call → PostgreSQL data + KB context injected together (RAG)
    5. Returns: ai_sections + context + kb_annotations
    """
    # ── Step 1: PostgreSQL data ────────────────────────────────
    ctx = build_warehouse_context(db)
    context_text = _context_to_prompt_text(ctx)

    # ── Step 2: KB Vector Store retrieval ─────────────────────
    kb_store = get_kb_store()
    # Inject the FULL source-grouped KB. The curated corpus (26 chunks spanning
    # statutory law, OEM schedules, ISO 55000/55001, SMRP, FMEA and Colombo climate)
    # is small enough to inject completely, guaranteeing no standard is dropped by
    # top-k retrieval — the strongest lever for grounded, high-quality report prose.
    kb_full_context = kb_store.build_full_kb_context()

    # ── Step 3: KB Annotations (deterministic — no LLM) ───────
    shap_enriched     = annotate_shap_features(ctx.get("top_shap_features", []))
    health_bands_kb   = annotate_health_bands(ctx.get("health_score_distribution", {}))
    benchmark_alerts  = compute_benchmark_alerts(ctx)
    ticket_cat_kb     = get_ticket_category_kb(ctx.get("ticket_category_breakdown", {}))
    recommendations   = generate_recommendations(ctx)
    service_interval  = get_service_interval_kb_text()
    oem_intervals     = get_oem_interval_reference()
    statutory_compliance = get_statutory_compliance_reference()
    fmea_criticality  = rank_fmea_criticality(ctx.get("critical_assets", []))
    climate_risk      = get_climate_risk_flags(ctx)

    kb_annotations = {
        "shap_enriched":         shap_enriched,
        "health_bands_kb":       health_bands_kb,
        "benchmark_alerts":      benchmark_alerts,
        "ticket_category_kb":    ticket_cat_kb,
        "recommendations":       recommendations,
        "service_interval_text": service_interval,
        # ── Enhanced deterministic, PDF-ready tables (grounded, no LLM) ──
        "oem_intervals":         oem_intervals,          # Toyota/Tata OEM tier tables
        "statutory_compliance":  statutory_compliance,   # Factories Ordinance 1942 intervals
        "fmea_criticality":      fmea_criticality,       # severity × occurrence ranking of critical assets
        "climate_risk":          climate_risk,           # Colombo climate-driven flags
    }

    # ── Step 4: LLM call with KB-grounded prompt ───────────────
    llm = _get_llm(temperature=0.25)

    combined_prompt = (
        f"LIVE DATABASE DATA:\n{context_text}\n\n"
        f"KNOWLEDGE BASE CONTEXT (ISO 55000 / SMRP Standards):\n{kb_full_context}"
    )

    messages = [
        SystemMessage(content=WAREHOUSE_SYSTEM_PROMPT),
        HumanMessage(content=f"Generate the full KB-Enhanced warehouse report:\n\n{combined_prompt}"),
    ]

    response = llm.invoke(messages)
    content = response.content.strip()

    # Strip code fences if model added them
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content).strip()

    # Parse AI JSON
    try:
        ai_sections = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", content)
        if match:
            try:
                ai_sections = json.loads(match.group())
            except json.JSONDecodeError:
                ai_sections = {"insight_summary": content, "risk_analysis": "",
                               "maintenance_intelligence": "", "pattern_and_trend": "", "conclusion": ""}
        else:
            ai_sections = {"insight_summary": content, "risk_analysis": "",
                           "maintenance_intelligence": "", "pattern_and_trend": "", "conclusion": ""}

    # Faithfulness guard: append authoritative, data-grounded trend facts to the
    # narrative and flag any LLM trend claim that contradicts the computed directions
    # (e.g. "costs trending upwards" while cost data falls, or attributing an
    # artifactual decline to "efficiency"). Prevents those errors standing in the PDF.
    ai_sections = _guard_narrative(ai_sections, ctx)

    return {
        "ai_sections":    ai_sections,
        "context":        ctx,
        "kb_annotations": kb_annotations,   # NEW — all KB enrichments for frontend
    }


# ═══════════════════════════════════════════════════════════════
# ASSET REPORT AGENT (Entrance stub — Asset Team implements internals)
# ═══════════════════════════════════════════════════════════════

def run_asset_agent(asset_id: str | None = None, db: Session | None = None) -> dict:
    """
    Asset Report Agent — entrance routing point.

    The Main Router Agent calls this when user intent is 'asset_report'.
    The asset section team should implement the full report logic here.
    Currently returns a structured stub response.

    Chatbot integration: The chatbot can trigger asset reports via POST /chat-route
    with a message like "Generate report for asset WH-VH-001".
    """
    # Basic asset lookup if id provided and db available
    asset_info = None
    if asset_id and db:
        try:
            from app.models import Asset, AssetFailurePrediction
            asset = db.query(Asset).filter(Asset.asset_code == asset_id).first()
            if asset:
                pred = db.query(AssetFailurePrediction).filter(
                    AssetFailurePrediction.asset_id == asset.id
                ).first()
                asset_info = {
                    "asset_code": asset.asset_code,
                    "name": asset.asset_name,
                    "type": asset.vehicle_type,
                    "status": asset.status,
                    "health_score": int(pred.health_score) if pred and pred.health_score else None,
                    "risk_level": pred.risk_level if pred else None,
                }
        except Exception:
            pass

    return {
        "agent": "asset_report_agent",
        "status": "entrance_stub",
        "message": "Asset Report Agent has been activated. The asset team's report logic will be called here.",
        "asset_id": asset_id,
        "asset_info": asset_info,
        "note": "Full implementation: asset section team. Entrance point ready for chatbot integration.",
    }


# ═══════════════════════════════════════════════════════════════
# MAIN ROUTER AGENT — Chatbot Integration Entry Point
# ═══════════════════════════════════════════════════════════════

ROUTER_SYSTEM_PROMPT = """
You are a smart report-routing AI for the PredictiX warehouse management system.
Users may ask for warehouse reports, asset-specific reports, or general questions.

Classify the user's message into EXACTLY one of these three categories:
- "warehouse_report"  → user wants a warehouse-level report, fleet summary, health report, operational overview
- "asset_report"      → user wants a report about a specific asset, vehicle, or asset ID
- "general_chat"      → anything else: greetings, general questions, help requests, chatbot queries

Return ONLY the category string. No explanation, no punctuation, no spaces.
"""


def route_request(user_message: str) -> str:
    """
    Main Router Agent — classifies intent for chatbot integration.
    Called by POST /warehouse-dashboard/chat-route
    Returns: 'warehouse_report' | 'asset_report' | 'general_chat'
    """
    llm = _get_llm(temperature=0.0)
    messages = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]
    response = llm.invoke(messages)
    intent = response.content.strip().lower().strip('"').strip("'").replace(" ", "_")

    if "warehouse" in intent:
        return "warehouse_report"
    elif "asset" in intent:
        return "asset_report"
    return "general_chat"
