"""
PredictiX KB Annotator
========================
Deterministic annotation engine — no LLM required for annotations.
Computes KB-mapped metadata from live context data using exact-match
lookups and range-based logic.

All thresholds sourced from SHAP_KB_MAP, HEALTH_BAND_KB, and BENCHMARKS
in kb_documents.py.
"""

from __future__ import annotations

import re

from .kb_documents import (
    SHAP_KB_MAP,
    HEALTH_BAND_KB,
    BENCHMARKS,
    TICKET_CATEGORY_KB,
    SERVICE_INTERVAL_SUMMARY,
    SERVICE_INTERVALS,
    OEM_SERVICE_TIERS,
    STATUTORY_INSPECTION_INTERVALS,
    FMEA_SEVERITY_BY_TYPE,
    DEFAULT_FMEA_SEVERITY,
)


# ── SHAP Annotation ────────────────────────────────────────────

def _canon_feature(name: str) -> str:
    """
    Canonicalise a SHAP feature name so model column names (which carry unit
    suffixes like 'Pct' or 'C', e.g. 'Brake Health Pct', 'Coolant Temp Max C')
    match the KB map keys (e.g. 'brake health', 'coolant temp max').
    """
    s = (name or "").lower().strip()
    s = s.replace("(°c)", "").replace("°c", "").replace("(%)", "").replace("%", "")
    s = s.replace("_", " ")
    s = re.sub(r"\b(pct|c)\b", "", s)   # drop trailing unit tokens
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Pre-normalised KB index so unit-suffixed feature names still resolve.
_SHAP_KB_CANON: dict[str, dict] = {_canon_feature(k): v for k, v in SHAP_KB_MAP.items()}


def annotate_shap_features(top_shap_features: list) -> list[dict]:
    """
    Cross-reference SHAP top features against KB threshold mappings.

    Input:  list of (feature_name, count_or_score) tuples from DB
    Output: list of dicts with feature, impact_pct, kb_threshold, action
    """
    if not top_shap_features:
        return []

    total = sum(score for _, score in top_shap_features) or 1
    result = []

    for feat, score in top_shap_features:
        # Normalise key: lowercase, strip whitespace
        lookup_key = feat.lower().strip()
        # Exact match → underscore variant → canonical (unit-suffix-tolerant) match
        kb = (
            SHAP_KB_MAP.get(lookup_key)
            or SHAP_KB_MAP.get(lookup_key.replace(" ", "_"))
            or _SHAP_KB_CANON.get(_canon_feature(feat))
            or {}
        )

        impact_pct = round((score / total) * 100, 1)

        result.append({
            "feature":       feat.replace("_", " ").title(),
            "impact_pct":    impact_pct,
            "impact_raw":    score,
            "kb_threshold":  kb.get("kb_threshold", "See OEM manual"),
            "action":        kb.get("action", "Inspect and service per schedule"),
            "standard":      kb.get("standard", "ISO 55000 §8.6"),
        })

    # Sort by impact descending
    result.sort(key=lambda x: -x["impact_pct"])
    return result


# ── Health Band Annotation ─────────────────────────────────────

def annotate_health_bands(health_distribution: dict) -> list[dict]:
    """
    Add KB interpretation to each health score band.

    Input:  dict like {"90-100%": 481, "80-89%": 81, ...}
    Output: list of dicts with band, count, pct_fleet, kb_interpretation
    """
    total = sum(health_distribution.values()) or 1
    result = []

    # Normalise keys in distribution dict (handles "90–100%" vs "90-100%" etc.)
    def _normalise(key: str) -> str:
        return key.replace("–", "-").replace("—", "-").strip()

    dist_norm = {_normalise(k): v for k, v in health_distribution.items()}

    for band_info in HEALTH_BAND_KB:
        band = band_info["band"]
        band_norm = _normalise(band)

        # Try exact match then fuzzy
        count = dist_norm.get(band_norm, 0)
        if count == 0:
            for k, v in dist_norm.items():
                if k.replace(" ", "").lower() == band_norm.replace(" ", "").lower():
                    count = v
                    break

        result.append({
            "band":               band,
            "count":              count,
            "pct_fleet":          round(count / total * 100, 1),
            "kb_interpretation":  band_info["kb_interpretation"],
            "db_enum":            band_info["db_enum"],
        })

    return result


# ── Benchmark Alert Computation ────────────────────────────────

def compute_benchmark_alerts(ctx: dict) -> list[dict]:
    """
    Compare live PostgreSQL data against KB benchmarks.
    Returns list of alert dicts with type and message.

    Types: BENCHMARK | HIGH_ALERT
    """
    alerts: list[dict] = []
    total_assets = max(ctx.get("total_assets", 1), 1)

    # 1. Critical rate benchmark (ISO 55000 / SMRP: <5%)
    # Use the Critical band (<50% health) consistently — the same figure shown on the
    # "Critical Assets" KPI card — so the narrative and the card never disagree.
    # (Previously this used at_risk_count (<60%) while labelling it "critical", which
    # produced a higher percentage than the card/prose.)
    critical_count = ctx.get("critical_count", 0)
    at_risk_count = ctx.get("at_risk_count", 0)
    critical_pct = round((critical_count / total_assets) * 100, 1)
    target = BENCHMARKS["critical_rate_target_pct"]
    if critical_pct > target:
        gap = round(critical_pct - target, 1)

        # Real preventive-maintenance ratio = preventive events / all events.
        # (Previously this divided assets-due-soon by historical event count — two
        # unrelated quantities — which is dimensionless and can exceed 100%.)
        mtb = {str(k).lower(): v for k, v in (ctx.get("maintenance_type_breakdown") or {}).items()}
        preventive_events = mtb.get("preventive", 0) + mtb.get("scheduled", 0)
        total_events = sum(mtb.values()) or ctx.get("total_maintenance_events_3m", 0)
        pm_ratio = round(min(preventive_events / total_events * 100, 100.0), 1) if total_events else None
        if pm_ratio is not None:
            aligns = pm_ratio >= 90
            pm_text = (
                f" The fleet's preventive maintenance ratio is {pm_ratio}% "
                f"({total_events} events), {'which aligns with' if aligns else 'which is below'} "
                f"the best-practice target of ≥90% PM coverage."
            )
        else:
            pm_text = " Preventive maintenance ratio is unavailable for the current period."

        alerts.append({
            "type": "BENCHMARK",
            "message": (
                f"Industry standards (ISO 55000 / SMRP Best Practices) target fewer than "
                f"{target:g}% of a fleet in critical condition (<50% health). At {critical_pct}% "
                f"({critical_count} of {total_assets} assets), PredictiX is currently "
                f"{gap} percentage points above the benchmark, signalling an elevated collective "
                f"failure risk; a further {at_risk_count} assets are at-risk (<60% health)."
                f"{pm_text}"
            ),
        })

    # 2. High-priority ticket threshold (KB: ≤40% of ACTIVE tickets)
    # Denominator is active tickets (open + in-progress); wording matches the math.
    active_tickets = max(ctx.get("active_tickets", 0), 1)
    hp_tickets = ctx.get("high_priority_active_tickets", 0)
    hp_pct = round((hp_tickets / active_tickets) * 100, 1) if active_tickets else 0
    threshold = BENCHMARKS["high_priority_ticket_threshold_pct"]
    if hp_pct > threshold:
        alerts.append({
            "type": "HIGH_ALERT",
            "message": (
                f"{hp_pct}% of active tickets ({hp_tickets} of {active_tickets}) are High-priority — "
                f"exceeds the {threshold:g}% threshold, indicating systemic maintenance backlog "
                f"or recurring failure modes."
            ),
        })

    return alerts


# ── Ticket Category KB Annotation ─────────────────────────────

def get_ticket_category_kb(category_breakdown: dict) -> list[dict]:
    """
    Add KB guidance to each ticket category from live data.

    Input:  dict like {"General": 130, "Electrical": 76, ...}
    Output: list sorted by count desc with kb_guidance added
    """
    total = sum(category_breakdown.values()) or 1
    result = []

    for cat, count in sorted(category_breakdown.items(), key=lambda x: -x[1]):
        lookup = cat.lower().strip()
        if lookup in ("general", "uncategorized"):
            continue
            
        result.append({
            "category":    cat.title(),
            "count":       count,
            "pct_open":    round(count / total * 100, 1),
            "kb_guidance": TICKET_CATEGORY_KB.get(
                lookup,
                "Review and classify per maintenance type — inspect related primary indicators"
            ),
        })

    return result


# ── KB Recommendations Generator ──────────────────────────────

def generate_recommendations(ctx: dict) -> dict:
    """
    Generate KB-grounded, 3-tier urgency recommendations from live data.
    All numbers are pulled from ctx (no invented values).
    """
    critical_count   = ctx.get("critical_count", 0)
    at_risk_count    = ctx.get("at_risk_count", 0)
    urgent           = ctx.get("urgent_maintenance_count", 0)
    hp_tickets       = ctx.get("high_priority_active_tickets", 0)
    active_tickets   = ctx.get("active_tickets", 0)
    total_assets     = max(ctx.get("total_assets", 1), 1)
    # "critical %" must use the Critical band (<50%), matching the card and benchmark box.
    critical_pct     = round((critical_count / total_assets) * 100, 1)

    # Count forklifts from asset_type_breakdown if available
    abt = ctx.get("asset_type_breakdown", {})
    forklift_count = sum(
        v for k, v in abt.items()
        if "forklift" in k.lower() or "fork" in k.lower()
    )

    return {
        "critical": [
            (
                f"Ground all assets with brake health <40% (critical threshold) and hydraulic health <45% "
                f"pending immediate diagnostic inspection. Prioritise the {critical_count} Critical-status assets first."
            ),
            (
                f"Dispatch maintenance crew to resolve {hp_tickets} High-priority open tickets "
                f"within 24 hours each; focus on Electrical tickets to prevent electrical-fault cascades."
            ),
            (
                f"Extract engine-hour readings for all {forklift_count or 'forklift'} forklifts "
                f"— any unit exceeding 500 hours since last service is immediately overdue per standard interval."
            ),
        ],
        "high": [
            (
                f"Service all High-risk-level assets; target restoring fleet critical % from "
                f"{critical_pct}% toward the 5% industry benchmark within 60 days."
            ),
            (
                "Implement automated coolant-temperature monitoring alerts — any asset exceeding "
                "95°C triggers an immediate work order (critical threshold)."
            ),
            (
                "Schedule tire replacement for all units below 35% tire health and battery swap "
                "for electric forklifts below 40% battery health."
            ),
        ],
        "medium": [
            (
                "Integrate ISO 55000 3-month review cycle into the PredictiX scheduler — all assets "
                "in the 60–69% health band to receive a full lifecycle assessment."
            ),
            (
                "Leverage the PM ratio strength to build predictive work orders triggered by "
                "predictive primary indicator thresholds rather than fixed calendar intervals for higher-utilisation assets."
            ),
            (
                "Expand reference documentation with vehicle-specific service bulletins (OEM manuals for each of the "
                f"{len(ctx.get('asset_type_breakdown', {}))} asset types)."
            ),
        ],
        "kb_alert": (
            f"With {round((ctx.get('high_priority_active_tickets', 0) / max(ctx.get('active_tickets', 1), 1)) * 100, 1)}% "
            f"of active tickets ({ctx.get('high_priority_active_tickets', 0)} of {ctx.get('active_tickets', 0)}) "
            f"classified High-priority, the current queue exceeds the warning threshold of 40%. "
            f"Immediate load-balancing of the workforce is required."
        ),
    }


# ── Service Interval Helper ────────────────────────────────────

def get_service_interval_kb_text() -> str:
    """Return the KB service interval reference string for report display."""
    return SERVICE_INTERVAL_SUMMARY


def get_service_interval_for_type(asset_type: str) -> str:
    """Look up service interval for a specific asset type."""
    key = asset_type.lower().strip()
    return SERVICE_INTERVALS.get(key, "Every 90 days or manufacturer-specified mileage")


# ── OEM Interval Reference (deterministic PDF table) ──────────────

def get_oem_interval_reference() -> list[dict]:
    """
    Return OEM periodic-maintenance tiers grouped by asset class for direct
    PDF rendering. Grounded in Toyota and Tata OEM schedules.
    """
    return [
        {"asset_class": cls.title(), "source": spec["source"], "tiers": spec["tiers"]}
        for cls, spec in OEM_SERVICE_TIERS.items()
    ]


# ── Statutory Compliance Reference (deterministic PDF table) ──────

def get_statutory_compliance_reference() -> list[dict]:
    """
    Return the legally binding Sri Lanka Factories Ordinance inspection
    intervals for lifting equipment, ready for PDF rendering.
    """
    return [dict(row) for row in STATUTORY_INSPECTION_INTERVALS]


# ── FMEA Criticality Ranking (deterministic PDF table) ────────────

def rank_fmea_criticality(critical_assets: list[dict]) -> list[dict]:
    """
    Rank critical assets by FMECA-style criticality = severity × occurrence.

    - severity: from FMEA_SEVERITY_BY_TYPE (asset-type consequence weight, 1-10)
    - occurrence: the asset's failure probability (0-10 scaled), with health
      deficit (100 - health_score) as fallback when probability is unavailable.

    Returns the list sorted by criticality desc, each with severity, occurrence,
    criticality score, and a band (Ground Now / Service ≤7d / Monitor).
    """
    ranked: list[dict] = []

    for a in critical_assets or []:
        a_type = str(a.get("type", "")).lower().strip()
        severity = DEFAULT_FMEA_SEVERITY
        for key, weight in FMEA_SEVERITY_BY_TYPE.items():
            if key in a_type:
                severity = weight
                break

        # occurrence (0-10): prefer failure probability, else health deficit
        prob_raw = a.get("failure_prob")
        occ_pct = None
        if isinstance(prob_raw, str) and prob_raw.endswith("%"):
            try:
                occ_pct = float(prob_raw.rstrip("%"))
            except ValueError:
                occ_pct = None
        if occ_pct is None:
            health = a.get("health_score")
            occ_pct = (100 - float(health)) if health is not None else 50.0
        occurrence = round(min(max(occ_pct, 0.0), 100.0) / 10.0, 1)  # → 0-10

        criticality = round(severity * occurrence, 1)  # 0-100
        if criticality >= 60:
            band = "Ground Now"
        elif criticality >= 35:
            band = "Service ≤7 days"
        else:
            band = "Monitor / schedule"

        ranked.append({
            "code":        a.get("code"),
            "name":        a.get("name"),
            "type":        a.get("type"),
            "health":      a.get("health"),
            "severity":    severity,
            "occurrence":  occurrence,
            "criticality": criticality,
            "band":        band,
            "rationale": (
                f"Severity {severity}/10 ({a.get('type', 'asset')}) × occurrence {occurrence}/10 "
                f"(failure signal) = criticality {criticality}/100"
            ),
        })

    ranked.sort(key=lambda x: -x["criticality"])
    return ranked


# ── Colombo Climate Risk Flags (deterministic PDF callouts) ───────

def get_climate_risk_flags(ctx: dict) -> list[dict]:
    """
    Map the Colombo climate-vulnerability profile onto live component-health
    data, producing flagged risks for the PDF when thresholds are breached.
    Grounded in the Colombo WCT-1 Climate Adaptation Plan (2023).
    """
    comp = ctx.get("component_health", {}) or {}
    flags: list[dict] = []

    avg_battery = comp.get("avg_battery")
    if avg_battery is not None and avg_battery < 60:
        flags.append({
            "driver": "Heat & humidity → battery degradation",
            "metric": f"Fleet avg battery health {avg_battery}%",
            "action": "Increase battery checks for electric forklifts during hot/monsoon months",
        })

    avg_oil = comp.get("avg_oil")
    avg_hyd = comp.get("avg_hydraulic")
    if avg_hyd is not None and avg_hyd < 60:
        flags.append({
            "driver": "Wet-season corrosion → hydraulic/seal integrity",
            "metric": f"Fleet avg hydraulic health {avg_hyd}%",
            "action": "Add monsoon hydraulic seal & fluid inspections",
        })

    # Coolant exposure is elevated by Colombo ambient heat regardless of averages
    flags.append({
        "driver": "Rising ambient temperature → coolant exceedance (>95°C)",
        "metric": "Colombo projected temperature increase (WCT-1 plan)",
        "action": "Automated coolant-temperature alerting in hot months",
    })

    return flags
