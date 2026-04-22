"""
PredictiX Knowledge Base Documents
====================================
All KB content is sourced from the PredictiX_KB_Enhanced_Warehouse_Report.pdf
and cross-referenced with the LankaLogix-Colombo Supabase database schema.

Database Analysis (from dump):
- pgvector extension installed: CREATE EXTENSION IF NOT EXISTS vector
- rag_source_type ENUM: maintenance_log, ticket, asset_description, report, manual, faq, sop
- asset_health_band ENUM: excellent, good, moderate, poor, critical
- maintenance_event_type ENUM: inspection, scheduled_service, preventive, corrective, repair, replacement, breakdown, other
- ticket_category ENUM: electrical, mechanical, software (+ general from data)
- Asset types: forklift_2_5t, forklift_3_0t, delivery_van_1_5t, light_truck_3_5t, mini_truck_1t, medium_truck_7t, heavy_truck_16t
"""

# ═══════════════════════════════════════════════════════════════
# SHAP FEATURE → KB THRESHOLD + ACTION MAP
# Source: PredictiX KB Enhanced Warehouse Report / ISO 55000 / SMRP
# ═══════════════════════════════════════════════════════════════

SHAP_KB_MAP: dict[str, dict] = {
    # Primary keys match feature names from PredictionFeatureImportance table
    "engine hours since last service": {
        "kb_threshold": ">480 hrs → overdue",
        "action": "Prioritise forklifts/trucks approaching 500 h",
        "standard": "OEM-aligned service interval (ISO 55000 §8.6)",
    },
    "engine_hours_since_last_service": {
        "kb_threshold": ">480 hrs → overdue",
        "action": "Prioritise forklifts/trucks approaching 500 h",
        "standard": "OEM-aligned service interval (ISO 55000 §8.6)",
    },
    "coolant temp max": {
        "kb_threshold": ">95°C → critical",
        "action": "Inspect cooling system on high-temp assets now",
        "standard": "SMRP Best Practice 2.2 — Thermal limit threshold",
    },
    "coolant_temp_max": {
        "kb_threshold": ">95°C → critical",
        "action": "Inspect cooling system on high-temp assets now",
        "standard": "SMRP Best Practice 2.2 — Thermal limit threshold",
    },
    "coolant temp max (°c)": {
        "kb_threshold": ">95°C → critical",
        "action": "Inspect cooling system on high-temp assets now",
        "standard": "SMRP Best Practice 2.2 — Thermal limit threshold",
    },
    "brake health": {
        "kb_threshold": "<40% → ground asset",
        "action": "Any asset below 40% brake health: remove from ops",
        "standard": "ISO 55000 §8.6 — Safety-critical component protocol",
    },
    "brake_health": {
        "kb_threshold": "<40% → ground asset",
        "action": "Any asset below 40% brake health: remove from ops",
        "standard": "ISO 55000 §8.6 — Safety-critical component protocol",
    },
    "brake health (%)": {
        "kb_threshold": "<40% → ground asset",
        "action": "Any asset below 40% brake health: remove from ops",
        "standard": "ISO 55000 §8.6 — Safety-critical component protocol",
    },
    "days since last service": {
        "kb_threshold": ">90 days → overdue",
        "action": "Cross-check service log vs. calendar",
        "standard": "SMRP BP 3.1 — Calendar-based PM trigger",
    },
    "days_since_last_service": {
        "kb_threshold": ">90 days → overdue",
        "action": "Cross-check service log vs. calendar",
        "standard": "SMRP BP 3.1 — Calendar-based PM trigger",
    },
    "tire health": {
        "kb_threshold": "<35% → critical",
        "action": "Replace tires on all assets below threshold",
        "standard": "ISO 55000 §8.6 — Load-bearing component limit",
    },
    "tire_health": {
        "kb_threshold": "<35% → critical",
        "action": "Replace tires on all assets below threshold",
        "standard": "ISO 55000 §8.6 — Load-bearing component limit",
    },
    "tire health (%)": {
        "kb_threshold": "<35% → critical",
        "action": "Replace tires on all assets below threshold",
        "standard": "ISO 55000 §8.6 — Load-bearing component limit",
    },
    "battery health": {
        "kb_threshold": "<40% → swap",
        "action": "Schedule battery replacements for electric forklifts",
        "standard": "SMRP BP 4.3 — Electric asset battery lifecycle",
    },
    "battery_health": {
        "kb_threshold": "<40% → swap",
        "action": "Schedule battery replacements for electric forklifts",
        "standard": "SMRP BP 4.3 — Electric asset battery lifecycle",
    },
    "battery health (%)": {
        "kb_threshold": "<40% → swap",
        "action": "Schedule battery replacements for electric forklifts",
        "standard": "SMRP BP 4.3 — Electric asset battery lifecycle",
    },
    "hydraulic health": {
        "kb_threshold": "<45% → inspect",
        "action": "Hydraulic oil flush + seal check on high-use forklifts",
        "standard": "ISO 55000 §8.6 — Fluid system integrity check",
    },
    "hydraulic_health": {
        "kb_threshold": "<45% → inspect",
        "action": "Hydraulic oil flush + seal check on high-use forklifts",
        "standard": "ISO 55000 §8.6 — Fluid system integrity check",
    },
    "hydraulic health (%)": {
        "kb_threshold": "<45% → inspect",
        "action": "Hydraulic oil flush + seal check on high-use forklifts",
        "standard": "ISO 55000 §8.6 — Fluid system integrity check",
    },
    "active fault code count": {
        "kb_threshold": ">0 active codes → investigate",
        "action": "Clear/investigate all active ECU fault codes",
        "standard": "SMRP BP 2.1 — OBD fault escalation policy",
    },
    "active_fault_code_count": {
        "kb_threshold": ">0 active codes → investigate",
        "action": "Clear/investigate all active ECU fault codes",
        "standard": "SMRP BP 2.1 — OBD fault escalation policy",
    },
}


# ═══════════════════════════════════════════════════════════════
# HEALTH BANDS → KB INTERPRETATION
# Mapped to asset_health_band ENUM from DB schema
# ═══════════════════════════════════════════════════════════════

HEALTH_BAND_KB: list[dict] = [
    {
        "band": "90–100%",
        "db_enum": "excellent",
        "kb_interpretation": "Optimal — maintain current schedule",
    },
    {
        "band": "80–89%",
        "db_enum": "good",
        "kb_interpretation": "Good — monitor; preventive care on-track",
    },
    {
        "band": "70–79%",
        "db_enum": "moderate",
        "kb_interpretation": "Moderate — schedule service within 2 weeks",
    },
    {
        "band": "60–69%",
        "db_enum": "poor",
        "kb_interpretation": "At-Risk — service within 7 days",
    },
    {
        "band": "Below 60%",
        "db_enum": "critical",
        "kb_interpretation": "Critical — immediate intervention required",
    },
]


# ═══════════════════════════════════════════════════════════════
# ASSET TYPE → SERVICE INTERVAL
# LankaLogix-Colombo fleet: 7 asset types from DB
# ═══════════════════════════════════════════════════════════════

SERVICE_INTERVALS: dict[str, str] = {
    "forklift 2.5t":       "Every 500 engine hours",
    "forklift_2_5t":       "Every 500 engine hours",
    "forklift 3.0t":       "Every 500 engine hours",
    "forklift_3_0t":       "Every 500 engine hours",
    "delivery van 1.5t":   "Every 60 days",
    "delivery_van_1_5t":   "Every 60 days",
    "light truck 3.5t":    "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "light_truck_3_5t":    "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "mini truck 1t":       "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "mini_truck_1t":       "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "medium truck 7t":     "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "medium_truck_7t":     "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "heavy truck 16t":     "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "heavy_truck_16t":     "Every 90 days or manufacturer-specified mileage, whichever comes first",
}

SERVICE_INTERVAL_SUMMARY = (
    "Forklifts: every 500 engine hours. "
    "Delivery Vans: every 60 days. "
    "Trucks (all classes): every 90 days or manufacturer-specified mileage, whichever comes first. "
    "Adherence to these intervals is the primary lever for moving assets out of the Critical bracket."
)


# ═══════════════════════════════════════════════════════════════
# KB BENCHMARKS
# Source: ISO 55000, SMRP Best Practices
# ═══════════════════════════════════════════════════════════════

BENCHMARKS: dict[str, float] = {
    "critical_rate_target_pct":          5.0,   # ISO 55000 / SMRP: <5% of fleet in critical condition
    "pm_coverage_target_pct":            90.0,  # SMRP BP: ≥90% preventive maintenance ratio
    "high_priority_ticket_threshold_pct": 40.0, # KB: ≤40% of open tickets should be high-priority
    "health_score_warning":              80.0,  # Fleet avg health should be ≥80% (KB floor)
    "cost_multiplier_critical":           2.7,  # Critical assets cost 2.7x healthy assets (KB cost model)
}


# ═══════════════════════════════════════════════════════════════
# TICKET CATEGORY → KB GUIDANCE
# Mapped to ticket_category ENUM: electrical, mechanical, software + general
# ═══════════════════════════════════════════════════════════════

TICKET_CATEGORY_KB: dict[str, str] = {
    "general":    "Includes inspection, scheduling, documentation — triage for electrical/mechanical root causes",
    "electrical": "Electrical faults linked to Battery Health (SHAP#6) — inspect battery & wiring harness",
    "mechanical": "Mechanical tickets correlate with Hydraulic Health (SHAP#7) — inspect seals & fluid",
    "software":   "Software/ECU faults linked to Active Fault Code Count (SHAP#8) — clear and investigate all active codes",
}


# ═══════════════════════════════════════════════════════════════
# MAINTENANCE EVENT TYPE → KB CLASSIFICATION
# Maps DB maintenance_event_type ENUM to PM vs Corrective
# ═══════════════════════════════════════════════════════════════

MAINTENANCE_TYPE_KB: dict[str, str] = {
    "preventive":        "PM",
    "inspection":        "PM",
    "scheduled_service": "PM",
    "corrective":        "Corrective",
    "repair":            "Corrective",
    "replacement":       "Corrective",
    "breakdown":         "Corrective",
    "other":             "Other",
}


# ═══════════════════════════════════════════════════════════════
# KB DOCUMENTS — Used for TF-IDF Vector Store RAG Retrieval
# Each document represents a KB chunk for semantic retrieval
# ═══════════════════════════════════════════════════════════════

KB_DOCUMENTS: list[dict] = [
    {
        "id": "kb_iso55000_critical_rate",
        "section": "ISO 55000 §8.6 — Fleet Risk Benchmarks",
        "tags": ["critical", "fleet", "benchmark", "risk", "iso55000"],
        "text": (
            "ISO 55000 and SMRP Best Practices specify that a healthy fleet should maintain fewer than 5% "
            "of assets in critical condition. A critical rate above this benchmark indicates systemic "
            "maintenance backlogs and elevates collective failure risk across the fleet. "
            "The benchmark gap is calculated as (actual critical % - 5%) to quantify deviation. "
            "Fleets exceeding 20% critical rate are classified as high systemic risk requiring emergency intervention."
        ),
    },
    {
        "id": "kb_smrp_pm_ratio",
        "section": "SMRP Best Practice — PM Coverage Standard",
        "tags": ["preventive", "maintenance", "pm", "ratio", "smrp"],
        "text": (
            "Industry gold standard for preventive maintenance (PM) coverage is ≥90% of all maintenance events. "
            "A PM ratio above 90% strongly correlates with lower unplanned downtime, reduced repair costs, "
            "and extended asset lifespan. PM ratios below 75% indicate reactive maintenance culture. "
            "At 99.0% PM coverage, a fleet exceeds the SMRP benchmark but must ensure scheduling frequency "
            "matches actual asset degradation rates, especially for high-utilisation forklifts."
        ),
    },
    {
        "id": "kb_service_intervals",
        "section": "OEM Service Intervals — LankaLogix Fleet",
        "tags": ["service", "interval", "forklift", "truck", "van", "schedule"],
        "text": (
            "Forklifts (all classes, 2.5T and 3.0T): every 500 engine hours. "
            "Delivery Vans (1.5T): every 60 days. "
            "Trucks (Mini 1T, Light 3.5T, Medium 7T, Heavy 16T): every 90 days or manufacturer-specified mileage, "
            "whichever comes first. Adherence to these intervals is the primary lever for moving assets "
            "out of the Critical bracket. Engine hours since last service exceeding 480 hours is classified "
            "as overdue per OEM intervals."
        ),
    },
    {
        "id": "kb_engine_hours",
        "section": "Engine Hours — Primary SHAP Failure Driver",
        "tags": ["engine", "hours", "shap", "forklift", "overdue", "service"],
        "text": (
            "Engine hours since last service is the top SHAP-identified failure driver across forklift and truck fleets, "
            "accounting for 17.0% of failure prediction impact. Threshold: >480 hours since last service is "
            "considered overdue. Any unit approaching 500 hours should be prioritised for immediate service scheduling. "
            "Forklifts operating in the LankaLogix Colombo distribution hub environment typically accumulate "
            "engine hours faster due to continuous loading and unloading cycles."
        ),
    },
    {
        "id": "kb_coolant_temperature",
        "section": "Coolant Temperature — Thermal Management Critical",
        "tags": ["coolant", "temperature", "thermal", "critical", "cooling"],
        "text": (
            "Coolant temperature maximum exceeding 95°C indicates thermal management failure and is classified "
            "as a critical alert (16.7% SHAP impact). The affected asset should be inspected immediately for "
            "cooling system integrity, fan operation, and coolant level. In Colombo's wet lowland climate, "
            "thermal stress is elevated due to high ambient humidity and temperature. Assets with coolant "
            "temp readings >95°C must be removed from heavy-load operations until inspected."
        ),
    },
    {
        "id": "kb_brake_health",
        "section": "Brake Health — Safety-Critical Component",
        "tags": ["brake", "safety", "critical", "ground", "health"],
        "text": (
            "Brake health is the third-highest SHAP failure driver at 16.4% impact. "
            "Any asset with brake health below 40% must be immediately removed from operations per "
            "ISO 55000 §8.6 safety-critical component protocol. Brake failure is the leading cause of "
            "warehouse injury incidents globally. Assets in the 40-60% brake health range should be "
            "scheduled for service within 7 days. Assets with brake health >80% are within safe operating range."
        ),
    },
    {
        "id": "kb_days_since_service",
        "section": "Days Since Last Service — Calendar PM Trigger",
        "tags": ["calendar", "service", "days", "pm", "schedule", "overdue"],
        "text": (
            "Days since last service (13.4% SHAP impact) is a calendar-based PM trigger per SMRP BP 3.1. "
            "Any asset exceeding 90 days without service is classified as overdue regardless of engine hours. "
            "For delivery vans (60-day interval), overdue threshold is 60 days. "
            "Cross-referencing engine hours against calendar days catches both usage-intensive and "
            "low-use assets that may have deteriorated without triggering hour-based alerts."
        ),
    },
    {
        "id": "kb_tire_health",
        "section": "Tire Health — Load-Bearing Component",
        "tags": ["tire", "tyre", "health", "critical", "load", "replacement"],
        "text": (
            "Tire health below 35% is classified as critical (12.9% SHAP impact). "
            "All assets below this threshold require immediate tire replacement. "
            "For heavy trucks (16T) and medium trucks (7T), tire health degradation accelerates under "
            "maximum load conditions. The KB recommends proactive tire assessment at the 50% mark "
            "to schedule replacements before the critical threshold is reached."
        ),
    },
    {
        "id": "kb_battery_health",
        "section": "Battery Health — Electric Forklift Lifecycle",
        "tags": ["battery", "electric", "forklift", "health", "swap", "lifecycle"],
        "text": (
            "Battery health below 40% triggers mandatory swap per SMRP BP 4.3 (9.8% SHAP impact). "
            "Electric forklifts (Forklift 2.5T and 3.0T classes) are the primary affected asset type. "
            "Battery health degradation accelerates in high-temperature environments like Colombo. "
            "The KB recommends battery health monitoring at weekly intervals for electric forklifts "
            "and replacement scheduling when health falls below 50% to avoid critical-threshold failures."
        ),
    },
    {
        "id": "kb_hydraulic_health",
        "section": "Hydraulic Health — Fluid System Integrity",
        "tags": ["hydraulic", "fluid", "seal", "forklift", "health", "inspect"],
        "text": (
            "Hydraulic health below 45% requires immediate inspection per ISO 55000 §8.6 (9.0% SHAP impact). "
            "Recommended action: hydraulic oil flush + seal check on high-use forklifts. "
            "Hydraulic system failures in warehouse forklifts are a primary cause of load-drop incidents. "
            "The 45% threshold triggers inspection; the 30% threshold triggers immediate grounding. "
            "Mechanical tickets correlate strongly with hydraulic health degradation."
        ),
    },
    {
        "id": "kb_fault_codes",
        "section": "Active Fault Code Count — ECU Diagnostics",
        "tags": ["fault", "code", "ecu", "obd", "electrical", "software"],
        "text": (
            "Any active ECU fault code count >0 triggers investigation per SMRP BP 2.1 (4.8% SHAP impact). "
            "All active OBD fault codes must be cleared and investigated immediately. "
            "Unresolved fault codes are primary drivers of electrical ticket volumes. "
            "The KB recommends weekly fault code sweeps for all assets with active fault codes, "
            "particularly for software and electrical ticket categories."
        ),
    },
    {
        "id": "kb_high_priority_tickets",
        "section": "Ticket Priority Thresholds — Escalation Policy",
        "tags": ["ticket", "priority", "high", "threshold", "escalation", "kb"],
        "text": (
            "KB warning threshold: ≤40% of open tickets should be classified High-priority. "
            "Exceeding this threshold indicates systemic fault escalation and elevated fleet-level failure risk. "
            "High-priority tickets should be triaged within 24 hours of creation. "
            "When high-priority tickets exceed 40% of open tickets, a fleet-wide safety audit is recommended. "
            "Electrical tickets are particularly important as they correlate with battery health SHAP driver."
        ),
    },
    {
        "id": "kb_cost_model",
        "section": "Maintenance Cost Model — Critical vs Healthy Assets",
        "tags": ["cost", "maintenance", "critical", "budget", "financial", "lkr"],
        "text": (
            "KB cost model: assets in the Below 60% health band incur approximately 2.7x the average "
            "maintenance cost relative to healthy assets (≥80% health). "
            "Rapid remediation of critical assets is therefore a high financial return priority. "
            "Total predicted maintenance cost should be compared against actual 3-month spend to identify "
            "budget variance. Significant underspend may indicate deferred maintenance risk."
        ),
    },
    {
        "id": "kb_health_distribution",
        "section": "Health Score Distribution — Fleet Assessment",
        "tags": ["health", "score", "distribution", "fleet", "assessment", "band"],
        "text": (
            "Fleet health assessment by band: "
            "90-100% (Excellent) — Optimal, maintain current schedule. "
            "80-89% (Good) — Monitor; preventive care on-track. "
            "70-79% (Moderate) — Schedule service within 2 weeks. "
            "60-69% (At-Risk/Poor) — Service within 7 days. "
            "Below 60% (Critical) — Immediate intervention required. "
            "A fleet with >36% assets below 60% represents a critical systemic risk requiring emergency "
            "maintenance mobilisation across all asset categories."
        ),
    },
    {
        "id": "kb_recommendations_framework",
        "section": "Recommendations Framework — 3-Tier Urgency",
        "tags": ["recommendations", "critical", "high", "medium", "urgency", "action"],
        "text": (
            "KB Recommendations are structured in three urgency tiers: "
            "CRITICAL (0-7 days): immediate safety-critical actions required — ground assets with brake/hydraulic below threshold, "
            "dispatch maintenance for high-priority tickets, extract engine-hour readings for all overdue assets. "
            "HIGH (7-30 days): service all high-risk assets, implement automated monitoring alerts, "
            "execute tire and battery replacement programs. "
            "MEDIUM (30-90 days): integrate ISO 55000 review cycles, build SHAP-triggered predictive work orders, "
            "expand KB with OEM vehicle-specific service bulletins."
        ),
    },
    {
        "id": "kb_lankalogix_context",
        "section": "LankaLogix Colombo — Warehouse Context",
        "tags": ["lankalogix", "colombo", "warehouse", "context", "climate", "fleet"],
        "text": (
            "LankaLogix Colombo warehouse (WH001) operates in a wet lowland climate at Biyagama Road, Kelaniya. "
            "Fleet comprises 7 asset types: Forklift 2.5T (223), Delivery Van 1.5T (218), Light Truck 3.5T (168), "
            "Mini Truck 1T (131), Forklift 3.0T (126), Medium Truck 7T (102), Heavy Truck 16T (32). "
            "Departments: Transportation (TRN), Electrical (ELC), Software (SFT), Mechanical (MEC), Admin (ADM). "
            "High humidity in Colombo accelerates battery degradation and coolant system corrosion, "
            "making these SHAP features particularly critical for this location."
        ),
    },
]
