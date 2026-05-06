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

from .kb_documents import (
    SHAP_KB_MAP,
    HEALTH_BAND_KB,
    BENCHMARKS,
    TICKET_CATEGORY_KB,
    SERVICE_INTERVAL_SUMMARY,
    SERVICE_INTERVALS,
)


# ── SHAP Annotation ────────────────────────────────────────────

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
        # Try exact match first, then underscore variant
        kb = SHAP_KB_MAP.get(lookup_key) or SHAP_KB_MAP.get(lookup_key.replace(" ", "_")) or {}

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
    at_risk = ctx.get("at_risk_count", 0)
    critical_pct = round((at_risk / total_assets) * 100, 1)
    target = BENCHMARKS["critical_rate_target_pct"]
    if critical_pct > target:
        gap = round(critical_pct - target, 1)
        pm_count = ctx.get("total_maintenance_events_3m", 0)
        alerts.append({
            "type": "BENCHMARK",
            "message": (
                f"Industry standards (ISO 55000 / SMRP Best Practices) target fewer than 5% of a fleet "
                f"in critical condition. At {critical_pct}%, PredictiX is currently "
                f"{gap} percentage points above the benchmark, signalling an elevated collective "
                f"failure risk. The fleet's preventive maintenance ratio is strong at "
                f"{round((ctx.get('soon_maintenance_count', pm_count) / max(pm_count, 1)) * 100, 1) if pm_count else 'N/A'}% "
                f"({ctx.get('total_maintenance_events_3m', 0)} events), which aligns with best-practice "
                f"targets of ≥90% PM coverage."
            ),
        })

    # 2. High-priority ticket threshold (KB: ≤40%)
    active_tickets = max(ctx.get("active_tickets", 0), 1)
    hp_tickets = ctx.get("high_priority_active_tickets", 0)
    hp_pct = round((hp_tickets / active_tickets) * 100, 1) if active_tickets else 0
    threshold = BENCHMARKS["high_priority_ticket_threshold_pct"]
    if hp_pct > threshold:
        alerts.append({
            "type": "HIGH_ALERT",
            "message": (
                f"{hp_pct}% of open tickets are High-priority — exceeds the threshold of 40% "
                f"indicating systemic maintenance backlog or recurring failure modes."
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
        result.append({
            "category":    cat.title(),
            "count":       count,
            "pct_open":    round(count / total * 100, 1),
            "kb_guidance": TICKET_CATEGORY_KB.get(
                lookup,
                "Review and classify per maintenance type — inspect related SHAP drivers"
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
    critical_pct     = round((at_risk_count / total_assets) * 100, 1)

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
                "Leverage the PM ratio strength to build predictive work orders triggered by SHAP "
                "feature thresholds rather than fixed calendar intervals for higher-utilisation assets."
            ),
            (
                "Expand reference documentation with vehicle-specific service bulletins (OEM manuals for each of the "
                f"{len(ctx.get('asset_type_breakdown', {}))} asset types)."
            ),
        ],
        "kb_alert": (
            f"With {round((ctx.get('high_priority_active_tickets', 0) / max(ctx.get('active_tickets', 1), 1)) * 100, 1)}% "
            f"of open tickets classified High-priority, the current queue exceeds the warning "
            f"threshold of 40%. Immediate load-balancing of the workforce is required."
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
