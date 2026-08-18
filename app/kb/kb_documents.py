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
    "oil life": {
        "kb_threshold": "<20% → drain & refill",
        "action": "Schedule oil and filter replacement immediately",
        "standard": "OEM Fluid Management Schedule",
    },
    "lifetime service count": {
        "kb_threshold": "High freq → review",
        "action": "Analyze service log for chronic failure modes",
        "standard": "SMRP BP 1.4 — Bad actor identification",
    },
    "operating hours last 30d": {
        "kb_threshold": ">200 hrs → high utilization",
        "action": "Accelerate preventive maintenance intervals",
        "standard": "SMRP BP 3.3 — Utilization-based scheduling",
    },
    "make model": {
        "kb_threshold": "OEM defect pattern",
        "action": "Cross-reference OEM service bulletins",
        "standard": "ISO 55000 §8.1 — OEM compliance",
    },
    "engine hours": {
        "kb_threshold": ">10,000 hrs → overhaul",
        "action": "Evaluate for major overhaul or replacement",
        "standard": "Asset Lifecycle Management Policy",
    },
    "temp": {
        "kb_threshold": ">95°C → critical",
        "action": "Inspect cooling system on high-temp assets now",
        "standard": "SMRP BP 2.2 — Thermal limit threshold",
    },
    "vibration": {
        "kb_threshold": ">0.5 in/s → investigate",
        "action": "Conduct vibration analysis & alignment check",
        "standard": "ISO 10816 — Mechanical vibration limits",
    },
    "age days": {
        "kb_threshold": ">10 yrs → end of life",
        "action": "Initiate capital replacement planning",
        "standard": "Asset Capital Depreciation Schedule",
    }
}


# ═══════════════════════════════════════════════════════════════
# HEALTH BANDS → KB INTERPRETATION
# Mapped to asset_health_band ENUM from DB schema
# ═══════════════════════════════════════════════════════════════

# Ranges are the canonical bands from app/services/health_bands.py, which are
# also the asset_health_band Postgres enum. They were previously a separate
# 90/80/70/60/50 scale whose db_enum column claimed, for example, that
# "90–100%" was excellent and "Below 50%" was critical.
#
# health_score is the mean component health *minus* a failure-probability and
# urgency penalty, so it peaks at 79 across the real fleet. On the old scale the
# top two bands were unreachable, "excellent" and "good" were always 0, and 621
# of 850 assets landed in "critical" — an alert covering three-quarters of a
# normally-worn fleet. The bands below are calibrated so each one is reachable
# and means the same thing here as on the dashboard and the assets list.
HEALTH_BAND_KB: list[dict] = [
    {
        "band": "80–100%",
        "db_enum": "excellent",
        "kb_interpretation": "Optimal — maintain current schedule",
    },
    {
        "band": "70–79%",
        "db_enum": "good",
        "kb_interpretation": "Good — monitor; preventive care on-track",
    },
    {
        "band": "50–69%",
        "db_enum": "moderate",
        "kb_interpretation": "Moderate — schedule service within 2 weeks",
    },
    {
        "band": "30–49%",
        "db_enum": "poor",
        "kb_interpretation": "At-Risk — schedule service within 14 days",
    },
    {
        # Canonical "Critical" cutoff for the whole report: health < 25%.
        # Matches the §1/§7 Critical-Assets KPI, the dashboard's Critical
        # Alerts count, and assets.health_band = 'critical'.
        "band": "Below 25%",
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
    "Adherence to these intervals is the primary lever for moving assets out of the Critical bracket:"
    "<ul style='margin:4px 0 0;padding-left:20px;'>"
    "<li><b>Forklifts:</b> every 500 engine hours</li>"
    "<li><b>Delivery Vans:</b> every 60 days</li>"
    "<li><b>Trucks (all classes):</b> every 90 days or manufacturer-specified mileage (whichever comes first)</li>"
    "</ul>"
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
    "general":    "Review operational logs to isolate root cause; expedite triage to prevent unclassified downtime",
    "electrical": "Prioritize battery and wiring inspections to maintain power stability and operational readiness",
    "mechanical": "Expedite hydraulic and structural servicing to prevent critical physical failures and safety compliance breaches",
    "software":   "Clear and investigate active ECU fault codes to ensure system reliability and mitigate deployment delays",
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

