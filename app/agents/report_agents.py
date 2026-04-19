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
    avg_health = db.query(func.avg(AssetFailurePrediction.health_score)).scalar() or 0
    avg_health_pct = int(avg_health)

    healthy_count  = db.query(func.count(AssetFailurePrediction.id)).filter(AssetFailurePrediction.health_score >= 80).scalar() or 0
    moderate_count = db.query(func.count(AssetFailurePrediction.id)).filter(AssetFailurePrediction.health_score.between(60, 79)).scalar() or 0
    at_risk_count  = db.query(func.count(AssetFailurePrediction.id)).filter(AssetFailurePrediction.health_score < 60).scalar() or 0
    critical_count = db.query(func.count(AssetFailurePrediction.id)).filter(AssetFailurePrediction.health_score < 50).scalar() or 0

    risk_level_dist = db.query(
        AssetFailurePrediction.risk_level, func.count(AssetFailurePrediction.id)
    ).group_by(AssetFailurePrediction.risk_level).all()
    risk_breakdown = {str(r).title() if r else "Unknown": c for r, c in risk_level_dist}

    avg_failure_prob = db.query(func.avg(AssetFailurePrediction.failure_probability)).scalar() or 0
    avg_failure_prob_pct = round(float(avg_failure_prob) * 100, 1)

    urgent_maintenance = db.query(func.count(AssetFailurePrediction.id)).filter(
        AssetFailurePrediction.days_until_maintenance <= 7,
        AssetFailurePrediction.days_until_maintenance.isnot(None),
    ).scalar() or 0

    soon_maintenance = db.query(func.count(AssetFailurePrediction.id)).filter(
        AssetFailurePrediction.days_until_maintenance <= 30,
        AssetFailurePrediction.days_until_maintenance.isnot(None),
    ).scalar() or 0

    avg_days_to_maintenance = db.query(func.avg(AssetFailurePrediction.days_until_maintenance)).scalar()
    avg_days_to_maintenance = int(avg_days_to_maintenance) if avg_days_to_maintenance else None

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

    # Health score distribution buckets
    health_scores = db.query(AssetFailurePrediction.health_score).filter(
        AssetFailurePrediction.health_score.isnot(None)
    ).all()
    health_buckets = {"90-100%": 0, "80-89%": 0, "70-79%": 0, "60-69%": 0, "Below 60%": 0}
    for (score,) in health_scores:
        if score >= 90:   health_buckets["90-100%"] += 1
        elif score >= 80: health_buckets["80-89%"] += 1
        elif score >= 70: health_buckets["70-79%"] += 1
        elif score >= 60: health_buckets["60-69%"] += 1
        else:             health_buckets["Below 60%"] += 1

    # Critical asset list (worst 8)
    critical_assets_q = (
        db.query(Asset, AssetFailurePrediction)
        .join(AssetFailurePrediction, Asset.id == AssetFailurePrediction.asset_id)
        .filter(AssetFailurePrediction.health_score < 60)
        .order_by(AssetFailurePrediction.health_score.asc())
        .limit(8)
        .all()
    )
    critical_assets_list = [
        {
            "code": a.asset_code,
            "name": a.asset_name or a.model or "Vehicle",
            "type": str(a.vehicle_type).replace("_", " ").title() if a.vehicle_type else "Unknown",
            "make": a.make or "N/A",
            "model": a.model or "N/A",
            "health_score": int(p.health_score),
            "health": f"{int(p.health_score)}%",
            "failure_prob": f"{round(float(p.failure_probability or 0) * 100, 1)}%",
            "risk": p.risk_level or "High",
            "days_to_service": p.days_until_maintenance,
            "status": a.status or "unknown",
        }
        for a, p in critical_assets_q
    ]

    # ── COST PREDICTIONS ──────────────────────────────────
    total_estimated_cost = db.query(func.sum(AssetCostPrediction.estimated_cost)).scalar() or 0
    avg_cost_per_asset   = db.query(func.avg(AssetCostPrediction.estimated_cost)).scalar() or 0
    min_cost_estimate    = db.query(func.min(AssetCostPrediction.min_cost)).scalar() or 0
    max_cost_estimate    = db.query(func.max(AssetCostPrediction.max_cost)).scalar() or 0
    cost_currency        = db.query(AssetCostPrediction.currency).first()
    currency             = cost_currency[0] if cost_currency else "LKR"

    # ── MAINTENANCE EVENTS ────────────────────────────────
    total_maintenance_3m = db.query(func.count(MaintenanceEvent.id)).filter(
        MaintenanceEvent.performed_at >= three_months_ago
    ).scalar() or 0

    actual_cost_3m = db.query(func.sum(MaintenanceEvent.cost_amount)).filter(
        MaintenanceEvent.performed_at >= three_months_ago
    ).scalar() or 0

    avg_downtime = db.query(func.avg(MaintenanceEvent.downtime_hours)).filter(
        MaintenanceEvent.performed_at >= three_months_ago
    ).scalar() or 0

    maintenance_type_rows = db.query(
        MaintenanceEvent.event_type, func.count(MaintenanceEvent.id)
    ).filter(MaintenanceEvent.performed_at >= three_months_ago).group_by(
        MaintenanceEvent.event_type
    ).all()
    maintenance_type_breakdown = {
        str(t).replace("_", " ").title() if t else "General": c for t, c in maintenance_type_rows
    }

    # Monthly maintenance costs over last 3 months
    monthly_maintenance = []
    for i in range(2, -1, -1):
        m_start = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        m_end   = (m_start + timedelta(days=32)).replace(day=1)
        m_cost  = db.query(func.sum(MaintenanceEvent.cost_amount)).filter(
            MaintenanceEvent.performed_at >= m_start,
            MaintenanceEvent.performed_at < m_end,
        ).scalar() or 0
        m_count = db.query(func.count(MaintenanceEvent.id)).filter(
            MaintenanceEvent.performed_at >= m_start,
            MaintenanceEvent.performed_at < m_end,
        ).scalar() or 0
        monthly_maintenance.append({
            "month": m_start.strftime("%B %Y"),
            "cost": int(m_cost),
            "events": m_count,
        })

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

    # Monthly ticket volumes over last 3 months
    ticket_trend = []
    for i in range(2, -1, -1):
        m_start = (now.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        m_end   = (m_start + timedelta(days=32)).replace(day=1)
        count   = db.query(func.count(Ticket.id)).filter(
            Ticket.created_at >= m_start,
            Ticket.created_at < m_end,
        ).scalar() or 0
        ticket_trend.append({"month": m_start.strftime("%B %Y"), "tickets": count})

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

    return {
        # Warehouse
        "warehouse_name": warehouse_name,
        "warehouse_city": warehouse_city,
        "warehouse_code": warehouse_code,
        "warehouse_active": warehouse_active,
        "department_count": dept_count,
        "report_date": now.strftime("%B %d, %Y"),
        "period": "Last 3 Months",

        # Assets
        "total_assets": total_assets,
        "active_assets": active_assets,
        "inactive_assets": inactive_assets,
        "under_maintenance_assets": under_maintenance,
        "retired_assets": retired_assets,
        "asset_type_breakdown": asset_type_breakdown,
        "asset_status_breakdown": asset_status_breakdown,
        "asset_category_breakdown": asset_category_breakdown,
        "avg_vehicle_age_years": round(float(avg_vehicle_age), 1),

        # Health
        "avg_health_pct": avg_health_pct,
        "healthy_count": healthy_count,
        "moderate_count": moderate_count,
        "at_risk_count": at_risk_count,
        "critical_count": critical_count,
        "avg_failure_prob_pct": avg_failure_prob_pct,
        "risk_breakdown": risk_breakdown,
        "health_score_distribution": health_buckets,
        "top_shap_features": top_shap_features,
        "urgent_maintenance_count": urgent_maintenance,
        "soon_maintenance_count": soon_maintenance,
        "avg_days_to_maintenance": avg_days_to_maintenance,
        "critical_assets": critical_assets_list,

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
        "monthly_maintenance_trend": monthly_maintenance,

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

▶ MAINTENANCE EVENTS (Last 3 Months)
  Total Events: {ctx['total_maintenance_events_3m']}
  Average Downtime per Event: {ctx['avg_downtime_hours']} hours
  By Type: {kv(ctx['maintenance_type_breakdown'])}
  Monthly Trend: {m_trend}

▶ TICKETS
  Total: {ctx['total_tickets']} | Active (Open+InProgress): {ctx['active_tickets']} | Open: {ctx['open_tickets']} | In Progress: {ctx['in_progress_tickets']} | Resolved: {ctx['resolved_tickets']} | Closed: {ctx['closed_tickets']}
  High-Priority Active Tickets: {ctx['high_priority_active_tickets']}
  Priority Breakdown: {kv(ctx['ticket_priority_breakdown'])}
  Category Breakdown: {kv(ctx['ticket_category_breakdown'])}
  Monthly Trend ({ctx['ticket_trend_direction']}): {t_trend}

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
  (B) KNOWLEDGE BASE context — ISO 55000 and SMRP maintenance standards relevant to the warehouse

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
   active users, and general warehouse status. Reference the KB benchmark (ISO 55000 5% critical target)
   if the critical rate exceeds it. Mention specific numbers from the data.

2. risk_analysis:
   Analyse the risk landscape using the KB context. State the count and percentage of critical/at-risk assets
   and compare to the ISO 55000 / SMRP 5% benchmark. Name the top AI-identified SHAP failure drivers
   and their KB-defined thresholds. Identify which asset types are most critical. Comment on failure probability
   and urgency — reference assets needing service within 7 days.

3. maintenance_intelligence:
   Outline the maintenance workload using KB standards. How many assets need urgent attention (≤7 days)?
   Compare the PM ratio against the SMRP 90% gold standard. Compare predicted cost vs actual 3M spend.
   Describe maintenance event breakdown and note average downtime. Reference KB service interval standards
   for the most common asset types (forklifts every 500 engine hours, vans every 60 days).

4. pattern_and_trend:
   Describe observable trends over the last 3 months. Is ticket volume increasing, decreasing, or stable?
   How are maintenance costs trending? Note patterns in ticket categories (electrical/mechanical/general)
   and their link to SHAP failure drivers. Comment on operational efficiency and KB-defined improvement opportunities.

5. conclusion:
   Write a comprehensive 3-month warehouse summary. Note the PM ratio strength and fleet health trajectory.
   Reference the split operational profile (strong PM culture vs high critical asset rate).
   Provide the top 3 recommended actions for management grounded in KB thresholds, with specific numbers.
   Close with the financial position and ticket resolution performance.

STRICT RULES:
- Use ONLY numbers from the provided data context. Never invent or estimate.
- Reference KB standards (ISO 55000, SMRP) naturally when the data warrants it.
- Do NOT include markdown, backticks, bullet points, or extra text outside the JSON.
- Each section must be a single flowing paragraph (no sub-headings inside values).
- KB context is grounding information — cite it when making threshold-based observations.
"""


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
    # Retrieve KB chunks relevant to the 5 report sections
    kb_chunks = {
        "fleet":       kb_store.get_all_text_for_section("fleet asset health overview critical rate benchmark"),
        "risk":        kb_store.get_all_text_for_section("shap failure drivers brake hydraulic engine hours coolant threshold"),
        "maintenance": kb_store.get_all_text_for_section("preventive maintenance pm ratio service interval cost downtime"),
        "tickets":     kb_store.get_all_text_for_section("ticket priority electrical mechanical fault code escalation"),
        "conclusion":  kb_store.get_all_text_for_section("recommendations action urgency critical high priority"),
    }
    kb_full_context = "\n\n".join([
        f"=== KB Context for {section.title()} ===\n{text}"
        for section, text in kb_chunks.items() if text
    ])

    # ── Step 3: KB Annotations (deterministic — no LLM) ───────
    shap_enriched     = annotate_shap_features(ctx.get("top_shap_features", []))
    health_bands_kb   = annotate_health_bands(ctx.get("health_score_distribution", {}))
    benchmark_alerts  = compute_benchmark_alerts(ctx)
    ticket_cat_kb     = get_ticket_category_kb(ctx.get("ticket_category_breakdown", {}))
    recommendations   = generate_recommendations(ctx)
    service_interval  = get_service_interval_kb_text()

    kb_annotations = {
        "shap_enriched":        shap_enriched,
        "health_bands_kb":      health_bands_kb,
        "benchmark_alerts":     benchmark_alerts,
        "ticket_category_kb":   ticket_cat_kb,
        "recommendations":      recommendations,
        "service_interval_text": service_interval,
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
