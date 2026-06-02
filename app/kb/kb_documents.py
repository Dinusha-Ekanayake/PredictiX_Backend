"""
PredictiX Knowledge Base Documents
====================================
KB content is cross-referenced with the LankaLogix-Colombo Supabase database schema.

Sources (oldest → newest):
- PredictiX_KB_Enhanced_Warehouse_Report (baseline ISO 55000 / SMRP synthesis)
- Sri Lanka Factories Ordinance No. 45 of 1942 — statutory inspection of lifting
  machinery, hoists/lifts, chains/ropes/tackle, machinery guarding
- Toyota 7FG/7FD/7FGK/7FDK Forklift Trucks Repair Manual (Sept 2000) — OEM periodic
  maintenance schedule (8h/40h/170h/500h/1000h/2000h)
- ABS Guidance Notes on Failure Mode and Effects Analysis (FMEA/FMECA), May 2015
- CEDR Implementation Guide for an ISO 55001 Asset Management System, Oct 2016
- Tata Motors Service Circular SC/2019/56 (PRIMA Lx 2825.K) — heavy-truck OEM service schedule
- Colombo Port (WCT-1) Climate Vulnerability & Adaptation Plan, March 2023

NOTE: Three supplied resources are image-only scans with no extractable text layer
(DoE O&M Best Practices Guide, SMRP Best Practices Metrics slide deck, "laws and
regulations.pdf"). They require OCR before they can be ingested; SMRP targets are
already represented in the baseline KB below.

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
        "kb_threshold": ">500 hrs → overdue",
        "action": "Prioritise forklifts/trucks approaching 500 h",
        "standard": "OEM-aligned service interval (ISO 55000 §8.6)",
    },
    "engine_hours_since_last_service": {
        "kb_threshold": ">500 hrs → overdue",
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
        "kb_interpretation": "At-Risk — schedule service within 14 days",
    },
    {
        "band": "50–59%",
        "db_enum": "poor",
        "kb_interpretation": "High Risk — service within 7 days",
    },
    {
        # Canonical "Critical" cutoff for the whole report: health < 50%.
        # Matches the §1/§7 Critical-Assets KPI and the benchmark narrative.
        "band": "Below 50%",
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
# OEM PERIODIC MAINTENANCE TIERS — for deterministic PDF tables
# Sources: Toyota 7FG/7FD Repair Manual; Tata Service Circular SC/2019/56
# ═══════════════════════════════════════════════════════════════

OEM_SERVICE_TIERS: dict[str, dict] = {
    "forklift": {
        "source": "Toyota 7FG/7FD/7FGK/7FDK Repair Manual",
        "tiers": [
            {"cadence": "Daily",      "trigger": "Every 8 engine hours",    "scope": "Operator check — service & parking brakes, leaks, tyres, controls"},
            {"cadence": "Weekly",     "trigger": "Every 40 engine hours",   "scope": "Fluid levels, battery, hydraulic lines, mast operation"},
            {"cadence": "Monthly",    "trigger": "Every 170 engine hours",  "scope": "Filters, lubrication, brake adjustment, electrical"},
            {"cadence": "3-Monthly",  "trigger": "Every 500 engine hours",  "scope": "Major service — engine, hydraulics, brakes (primary PM lever)"},
            {"cadence": "6-Monthly",  "trigger": "Every 1000 engine hours", "scope": "Deeper inspection, periodic part checks"},
            {"cadence": "Annual",     "trigger": "Every 2000 engine hours", "scope": "Overhaul + periodic replacement of parts and lubricants"},
        ],
    },
    "truck": {
        "source": "Tata Motors Service Circular SC/2019/56 (PRIMA Lx 2825.K)",
        "tiers": [
            {"cadence": "Daily",       "trigger": "Pre-trip check",                 "scope": "Air-filter-clogging indicator, service & parking brake function"},
            {"cadence": "1st Service", "trigger": "500 hours / 365 days",           "scope": "First scheduled service (whichever first)"},
            {"cadence": "2nd Service", "trigger": "1000 hours / 730 days",          "scope": "Drivetrain, brakes, tyre rotation & alignment"},
            {"cadence": "3rd Service", "trigger": "2000 hours / 1095 days",         "scope": "Major scheduled service"},
            {"cadence": "Ongoing",     "trigger": "~Every 1000 hours / annually",   "scope": "Hours-or-days, whichever comes first"},
        ],
    },
    "van": {
        "source": "LankaLogix OEM-aligned interval",
        "tiers": [
            {"cadence": "Routine", "trigger": "Every 60 days", "scope": "Delivery van scheduled service"},
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# STATUTORY INSPECTION — Sri Lanka Factories Ordinance No. 45 of 1942
# Legally binding floor; overrides OEM/predictive triggers where stricter
# ═══════════════════════════════════════════════════════════════

STATUTORY_INSPECTION_INTERVALS: list[dict] = [
    {
        "equipment": "Hoist or lift",
        "interval_months": 12,
        "by": "Competent person",
        "record": "General register within 14 days",
        "reference": "Factories Ordinance No. 45 of 1942, s. 27(2)",
    },
    {
        "equipment": "Chains, ropes & lifting tackle (in use)",
        "interval_months": 6,
        "by": "Competent person",
        "record": "Register of all tackle; SWL certificate before first use",
        "reference": "Factories Ordinance No. 45 of 1942, s. 28(d)–(e)",
    },
    {
        "equipment": "Chains & lifting tackle — annealing",
        "interval_months": 14,
        "by": "Heat treatment (6 months for ≤½-inch / molten-metal use)",
        "record": "Register",
        "reference": "Factories Ordinance No. 45 of 1942, s. 28(f)",
    },
    {
        "equipment": "Lifting-machine parts & gear (incl. forklift mast, hooks, anchoring)",
        "interval_months": 14,
        "by": "Competent person",
        "record": "Register of every examination",
        "reference": "Factories Ordinance No. 45 of 1942, s. 29(2)",
    },
]


# ═══════════════════════════════════════════════════════════════
# FMEA SEVERITY WEIGHTS BY ASSET TYPE (1–10 scale)
# Source: ABS FMEA Guidance criticality logic applied to fleet
# Criticality = severity (consequence) × occurrence (failure probability)
# ═══════════════════════════════════════════════════════════════

FMEA_SEVERITY_BY_TYPE: dict[str, int] = {
    "forklift":      9,  # lifting + pedestrian proximity → load-drop / crush risk
    "heavy truck":   9,  # mass + load → high-consequence road failure
    "medium truck":  8,
    "light truck":   7,
    "mini truck":    6,
    "delivery van":  6,
}
DEFAULT_FMEA_SEVERITY = 7


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
            "out of the Critical bracket. Engine hours since last service exceeding 500 hours is classified "
            "as overdue per OEM intervals."
        ),
    },
    {
        "id": "kb_engine_hours",
        "section": "Engine Hours — Primary SHAP Failure Driver",
        "tags": ["engine", "hours", "shap", "forklift", "overdue", "service"],
        "text": (
            "Engine hours since last service is the top SHAP-identified failure driver across forklift and truck fleets, "
            "accounting for 17.0% of failure prediction impact. Threshold: >500 hours since last service is "
            "considered overdue and should be prioritised for immediate service scheduling. "
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

    # ─────────────────────────────────────────────────────────────
    # ENHANCED KB — Statutory, OEM, FMEA, ISO 55001 & Climate sources
    # (appended; baseline ISO 55000 / SMRP documents above are retained)
    # ─────────────────────────────────────────────────────────────
    {
        "id": "kb_factories_ordinance_lifting",
        "section": "Sri Lanka Factories Ordinance No. 45 of 1942 — Statutory Lifting-Equipment Inspection",
        "tags": ["legal", "compliance", "statutory", "forklift", "hoist", "lifting", "inspection",
                 "sri lanka", "factories ordinance", "register", "safety"],
        "source": "Factories Ordinance No. 45 of 1942 (Sri Lanka), ss. 27–29",
        "text": (
            "Sri Lankan law (Factories Ordinance No. 45 of 1942) imposes mandatory inspection intervals on "
            "warehouse lifting equipment that operate ALONGSIDE OEM service intervals and override them where stricter. "
            "Section 27(2): every hoist or lift must be thoroughly examined by a competent person at least once "
            "every 12 months, with the report entered in the general register within 14 days. "
            "Section 28(d): all chains, ropes and lifting tackle in use must be examined by a competent person at least "
            "once every 6 months; section 28(f): chains and lifting tackle must be annealed at least once every 14 months "
            "(every 6 months for half-inch-or-smaller chain or chains used near molten metal). "
            "Section 29(2): all parts and working gear of every lifting machine (including forklift masts, hooks and "
            "anchoring appliances) must be examined by a competent person at least once every 14 months, with a register kept. "
            "Forklifts are lifting machines: any unit overdue against these statutory dates is non-compliant regardless of "
            "engine-hour status, and must be flagged for competent-person examination before further use."
        ),
    },
    {
        "id": "kb_factories_ordinance_safety",
        "section": "Sri Lanka Factories Ordinance No. 45 of 1942 — Machinery Guarding & Safe Working Load",
        "tags": ["legal", "compliance", "safety", "guarding", "fencing", "safe working load",
                 "sri lanka", "factories ordinance", "brake"],
        "source": "Factories Ordinance No. 45 of 1942 (Sri Lanka), ss. 16–28",
        "text": (
            "The Factories Ordinance requires every dangerous part of machinery and every transmission part to be "
            "securely fenced or guarded while in motion, and fencing to be maintained and kept in position. "
            "No chain, rope or lifting tackle may be used for any load exceeding its marked safe working load (SWL), "
            "and new lifting tackle must be tested and certified with its SWL before first use. "
            "This statutory duty reinforces the KB safety-critical protocol: an asset with brake health below 40% or a "
            "lifting component without a valid SWL certificate constitutes an unsafe machine and must be removed from "
            "operation until inspected and certified — a legal obligation, not merely a maintenance preference."
        ),
    },
    {
        "id": "kb_oem_forklift_intervals_toyota",
        "section": "Toyota 7FG/7FD Forklift — OEM Periodic Maintenance Schedule",
        "tags": ["oem", "forklift", "toyota", "service", "interval", "engine hours", "periodic",
                 "preventive", "schedule"],
        "source": "Toyota 7FG/7FD/7FGK/7FDK Forklift Trucks Repair Manual (Sept 2000), Periodic Maintenance",
        "text": (
            "The Toyota 7FG/7FD forklift OEM schedule defines five tiered periodic-inspection intervals that ground "
            "the 500-engine-hour KB benchmark: every 8 hours (daily operator check), every 40 hours (weekly), "
            "every 170 hours (monthly), every 500 hours (3-monthly major service — engine, hydraulics, brakes), "
            "every 1000 hours (6-monthly), and every 2000 hours (annual overhaul, including periodic replacement of "
            "parts and lubricants). Daily checks include service and parking brake function; the 500-hour service is "
            "the primary preventive lever. Because LankaLogix forklifts in the Colombo hub accumulate engine hours "
            "rapidly under continuous load cycles, units approaching 500 hours since last service should be scheduled "
            "before the interval lapses rather than after."
        ),
    },
    {
        "id": "kb_oem_truck_intervals_tata",
        "section": "Tata PRIMA Heavy Truck — OEM Service & Free-Service Schedule",
        "tags": ["oem", "truck", "tata", "heavy truck", "service", "interval", "schedule", "preventive"],
        "source": "Tata Motors Service Circular SC/2019/56 — PRIMA Lx 2825.K TC BS-IV 6X4",
        "text": (
            "The Tata PRIMA heavy-truck OEM free-service schedule is dual-triggered by operating hours OR calendar days, "
            "whichever comes first: 1st service at 500 hours / 365 days, 2nd at 1000 hours / 730 days, 3rd at 2000 hours / "
            "1095 days, and subsequent services at roughly 1000-hour / 365-day steps. Daily operator duties include "
            "checking the air-filter-clogging indicator and verifying service and parking brake function; tyre rotation "
            "and wheel alignment follow the service schedule. This OEM pattern substantiates the KB rule that trucks "
            "(Mini 1T, Light 3.5T, Medium 7T, Heavy 16T) are serviced every ~90 days or at manufacturer-specified "
            "mileage/hours, whichever comes first, with calendar overdue taking precedence for low-utilisation units."
        ),
    },
    {
        "id": "kb_fmea_methodology",
        "section": "FMEA / FMECA — Risk-Based Failure Prioritisation (ABS Guidance)",
        "tags": ["fmea", "fmeca", "risk", "criticality", "severity", "occurrence", "detection",
                 "rpn", "failure mode", "shap", "prioritisation"],
        "source": "ABS Guidance Notes on Failure Mode and Effects Analysis (FMEA) for Classification, May 2015",
        "text": (
            "FMEA (Failure Mode and Effects Analysis) systematically identifies each component's failure modes, their "
            "effects, and the means of detection, then ranks them so that effort and resources are commensurate with risk. "
            "FMECA extends FMEA with a criticality ranking that combines the SEVERITY of a failure's consequence with its "
            "probability of OCCURRENCE (and, for a Risk Priority Number, DETECTION difficulty): criticality ≈ severity × "
            "occurrence, RPN = severity × occurrence × detection. High-severity AND high-occurrence items demand corrective "
            "action first. This maps directly onto PredictiX SHAP outputs: a SHAP failure driver is the 'occurrence' signal "
            "and the asset's role (e.g. brake = safety-critical) is the 'severity' signal — high-SHAP brake/hydraulic faults "
            "are the highest-criticality items and should head the remediation queue."
        ),
    },
    {
        "id": "kb_fmea_components",
        "section": "FMEA Applied to Fleet Components — Severity Weighting",
        "tags": ["fmea", "criticality", "brake", "hydraulic", "coolant", "battery", "tire",
                 "severity", "safety", "ground asset"],
        "source": "ABS FMEA Guidance (May 2015) applied to LankaLogix fleet component set",
        "text": (
            "Applying FMECA severity weighting to the LankaLogix component set: brake and steering failures carry the "
            "highest severity (potential injury/loss-of-control → immediate grounding), hydraulic and lifting-mast failures "
            "are high severity (load-drop risk), coolant/thermal failures are high severity for engine integrity, while "
            "tyre, battery and oil degradation are moderate severity but high occurrence. Combining this with SHAP occurrence "
            "frequency, an asset showing a high-SHAP brake-health driver below 40% is a maximum-criticality item (high severity "
            "× high occurrence) and must be grounded; a high-occurrence but moderate-severity item (e.g. tyre health <35%) is "
            "scheduled, not grounded. Use the criticality product — not the SHAP rank alone — to order the work queue."
        ),
    },
    {
        "id": "kb_iso55001_ams",
        "section": "ISO 55001 — Asset Management System Framework (CEDR Implementation Guide)",
        "tags": ["iso55001", "iso 55001", "asset management", "samp", "leadership", "policy",
                 "pdca", "lifecycle", "governance", "risk-based"],
        "source": "CEDR Implementation Guide for an ISO 55001 Asset Management System (Oct 2016)",
        "text": (
            "ISO 55001 specifies a managed Asset Management System (AMS) rather than ad-hoc maintenance. Its backbone is a "
            "Strategic Asset Management Plan (SAMP) that turns organisational objectives into an asset management policy, "
            "objectives and plans, executed under a Plan-Do-Check-Act improvement cycle. It requires demonstrable top-management "
            "leadership and commitment, a risk-based approach to decision-making, and management of assets across their whole "
            "lifecycle. For PredictiX this means the warehouse report is not just a status snapshot: critical-rate, PM-ratio and "
            "SHAP findings should feed a documented SAMP review cycle with named ownership, closing the Check-Act loop on every "
            "reporting period rather than treating each report in isolation."
        ),
    },
    {
        "id": "kb_iso55001_lifecycle_cost",
        "section": "ISO 55001 — Whole-Lifecycle Cost Decision-Making",
        "tags": ["iso55001", "lifecycle cost", "lcc", "cost", "budget", "whole-life", "replacement",
                 "value", "financial"],
        "source": "CEDR Implementation Guide for an ISO 55001 Asset Management System (Oct 2016)",
        "text": (
            "ISO 55001 asset decisions must consider whole Lifecycle Cost (LCC) — acquisition, operation, maintenance and "
            "disposal — to balance cost, risk and performance rather than minimising short-term spend. This reframes the KB "
            "cost model: a critical-band asset costing ~2.7x in maintenance may still be worth retaining if its remaining "
            "whole-life value exceeds replacement LCC, whereas repeated corrective spend approaching replacement cost signals an "
            "LCC-driven replacement decision. Budget underspend against predicted maintenance cost should be read as deferred "
            "lifecycle risk, not as a saving, and surfaced explicitly in the financial section of the report."
        ),
    },
    {
        "id": "kb_colombo_climate_adaptation",
        "section": "Colombo Climate Vulnerability — Equipment Impact & Adaptation (WCT-1 Plan 2023)",
        "tags": ["colombo", "climate", "temperature", "humidity", "rainfall", "corrosion", "thermal",
                 "sea level", "adaptation", "monsoon", "battery", "coolant"],
        "source": "Colombo Port (WCT-1) Climate Vulnerability & Adaptation Plan, March 2023",
        "text": (
            "The Colombo WCT-1 climate assessment projects rising mean annual temperature, increasing maximum daytime "
            "temperatures, greater rainfall variability and intensity, sea-level rise, and more frequent extreme heat and "
            "high-wind events for the Colombo coastal zone. For ground fleet this elevates three KB SHAP drivers specifically: "
            "higher ambient heat raises coolant-temperature exceedance risk (>95°C critical), sustained heat and humidity "
            "accelerate battery degradation (electric forklifts) and electrical/ECU corrosion, and wet-season flooding raises "
            "brake and undercarriage corrosion. Recommended adaptation: increase inspection frequency for cooling, battery and "
            "electrical systems during the monsoon and hot months, and treat Colombo-location assets as a higher-occurrence "
            "population than a temperate baseline would imply."
        ),
    },
    {
        "id": "kb_compliance_three_layer",
        "section": "Three-Layer Maintenance Compliance Model",
        "tags": ["compliance", "iso55000", "iso55001", "legal", "oem", "interval", "framework",
                 "audit", "standard", "summary"],
        "source": "Synthesis: ISO 55000/55001 + Factories Ordinance 1942 + Toyota/Tata OEM schedules",
        "text": (
            "PredictiX maintenance compliance is governed by three stacked layers, and an asset must satisfy ALL of them. "
            "Layer 1 — Statutory (Sri Lanka Factories Ordinance 1942): hoists/lifts examined every 12 months, lifting tackle "
            "every 6 months, lifting-machine gear every 14 months, with registers kept; non-negotiable and legally enforceable. "
            "Layer 2 — OEM intervals: Toyota forklifts every 500 engine hours (with 8h/40h/170h/1000h/2000h tiers), Tata/heavy "
            "trucks every ~1000 hours or annually, vans every 60 days. Layer 3 — Standards & predictive (ISO 55000/55001 + SMRP "
            "+ SHAP): <5% critical, ≥90% PM ratio, ≤40% high-priority tickets, risk-based SAMP review. The binding requirement "
            "for any asset is the STRICTEST applicable trigger across all three layers — whichever falls due first."
        ),
    },
]
