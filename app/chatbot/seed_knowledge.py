"""Seeding script for PredictiX Knowledge Base.

Stores structured chunks from the baseline and enhanced knowledge base documents into
the Supabase `knowledge_base` table, generating vector embeddings for each chunk via the
HuggingFace sentence-transformers API.

Uses direct SQLAlchemy DB Session to bypass any Supabase Row-Level Security (RLS) constraints.
"""
from __future__ import annotations

import logging
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db import SessionLocal
from sqlalchemy import text
from app.ai.services.knowledge_service import embed_text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("seed_knowledge")

# ═══════════════════════════════════════════════════════════════
# RAW DATA STRUCTURES FROM USER REQUEST
# ═══════════════════════════════════════════════════════════════

SHAP_KB_MAP = {
    "engine_hours_since_last_service": {
        "kb_threshold": ">500 hrs → overdue",
        "action": "Prioritise forklifts/trucks approaching 500 h",
        "standard": "OEM-aligned service interval (ISO 55000 §8.6)",
    },
    "coolant_temp_max": {
        "kb_threshold": ">95°C → critical",
        "action": "Inspect cooling system on high-temp assets now",
        "standard": "SMRP Best Practice 2.2 — Thermal limit threshold",
    },
    "brake_health": {
        "kb_threshold": "<40% → ground asset",
        "action": "Any asset below 40% brake health: remove from ops",
        "standard": "ISO 55000 §8.6 — Safety-critical component protocol",
    },
    "days_since_last_service": {
        "kb_threshold": ">90 days → overdue",
        "action": "Cross-check service log vs. calendar",
        "standard": "SMRP BP 3.1 — Calendar-based PM trigger",
    },
    "tire_health": {
        "kb_threshold": "<35% → critical",
        "action": "Replace tires on all assets below threshold",
        "standard": "ISO 55000 §8.6 — Load-bearing component limit",
    },
    "battery_health": {
        "kb_threshold": "<40% → swap",
        "action": "Schedule battery replacements for electric forklifts",
        "standard": "SMRP BP 4.3 — Electric asset battery lifecycle",
    },
    "hydraulic_health": {
        "kb_threshold": "<45% → inspect",
        "action": "Hydraulic oil flush + seal check on high-use forklifts",
        "standard": "ISO 55000 §8.6 — Fluid system integrity check",
    },
    "active_fault_code_count": {
        "kb_threshold": ">0 active codes → investigate",
        "action": "Clear/investigate all active ECU fault codes",
        "standard": "SMRP BP 2.1 — OBD fault escalation policy",
    },
}

HEALTH_BAND_KB = [
    {"band": "60–100%", "db_enum": "excellent", "kb_interpretation": "Optimal — maintain current schedule"},
    {"band": "50–59%", "db_enum": "good", "kb_interpretation": "Good — monitor; preventive care on-track"},
    {"band": "38–49%", "db_enum": "moderate", "kb_interpretation": "Moderate — schedule service within 2 weeks"},
    {"band": "25–37%", "db_enum": "poor", "kb_interpretation": "At-Risk — schedule service within 14 days"},
    {"band": "Below 25%", "db_enum": "critical", "kb_interpretation": "Critical — immediate intervention required"},
]

SERVICE_INTERVALS = {
    "forklift 2.5t": "Every 500 engine hours",
    "forklift 3.0t": "Every 500 engine hours",
    "delivery van 1.5t": "Every 60 days",
    "light truck 3.5t": "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "mini truck 1t": "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "medium truck 7t": "Every 90 days or manufacturer-specified mileage, whichever comes first",
    "heavy truck 16t": "Every 90 days or manufacturer-specified mileage, whichever comes first",
}

STATUTORY_INSPECTION_INTERVALS = [
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

BENCHMARKS = {
    "critical_rate_target_pct": 5.0,
    "pm_coverage_target_pct": 90.0,
    "high_priority_ticket_threshold_pct": 40.0,
    "health_score_warning": 80.0,
    "cost_multiplier_critical": 2.7,
}

TICKET_CATEGORY_KB = {
    "general": "Includes inspection, scheduling, documentation — triage for electrical/mechanical root causes",
    "electrical": "Electrical faults linked to Battery Health (SHAP#6) — inspect battery & wiring harness",
    "mechanical": "Mechanical faults correlate with Hydraulic Health (SHAP#7) — inspect seals & fluid",
    "software": "Software/ECU faults linked to Active Fault Code Count (SHAP#8) — clear and investigate all active codes",
}

KB_DOCUMENTS = [
    {
        "title": "ISO 55000 §8.6 — Fleet Risk Benchmarks",
        "category": "Policies",
        "tags": ["critical", "fleet", "benchmark", "risk", "iso55000"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "ISO 55000 and SMRP Best Practices specify that a healthy fleet should maintain fewer than 5% "
            "of assets in critical condition. A critical rate above this benchmark indicates systemic "
            "maintenance backlogs and elevates collective failure risk across the fleet. "
            "The benchmark gap is calculated as (actual critical % - 5%) to quantify deviation. "
            "Fleets exceeding 20% critical rate are classified as high systemic risk requiring emergency intervention."
        ),
    },
    {
        "title": "SMRP Best Practice — PM Coverage Standard",
        "category": "Operations",
        "tags": ["preventive", "maintenance", "pm", "ratio", "smrp"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Industry gold standard for preventive maintenance (PM) coverage is ≥90% of all maintenance events. "
            "A PM ratio above 90% strongly correlates with lower unplanned downtime, reduced repair costs, "
            "and extended asset lifespan. PM ratios below 75% indicate reactive maintenance culture. "
            "At 99.0% PM coverage, a fleet exceeds the SMRP benchmark but must ensure scheduling frequency "
            "matches actual asset degradation rates, especially for high-utilisation forklifts."
        ),
    },
    {
        "title": "OEM Service Intervals — LankaLogix Fleet",
        "category": "Maintenance",
        "tags": ["service", "interval", "forklift", "truck", "van", "schedule"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Forklifts (all classes, 2.5T and 3.0T): every 500 engine hours. "
            "Delivery Vans (1.5T): every 60 days. "
            "Trucks (Mini 1T, Light 3.5T, Medium 7T, Heavy 16T): every 90 days or manufacturer-specified mileage, "
            "whichever comes first. Adherence to these intervals is the primary lever for moving assets "
            "out of the Critical bracket. Engine hours since last service exceeding 500 hours is classified "
            "as overdue per OEM intervals."
        ),
    },
    {
        "title": "Engine Hours — Primary SHAP Failure Driver",
        "category": "Troubleshooting",
        "tags": ["engine", "hours", "shap", "forklift", "overdue", "service"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Engine hours since last service is the top SHAP-identified failure driver across forklift and truck fleets, "
            "accounting for 17.0% of failure prediction impact. Threshold: >500 hours since last service is "
            "considered overdue and should be prioritised for immediate service scheduling. "
            "Forklifts operating in the LankaLogix Colombo distribution hub environment typically accumulate "
            "engine hours faster due to continuous loading and unloading cycles."
        ),
    },
    {
        "title": "Coolant Temperature — Thermal Management Critical",
        "category": "Troubleshooting",
        "tags": ["coolant", "temperature", "thermal", "critical", "cooling"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Coolant temperature maximum exceeding 95°C indicates thermal management failure and is classified "
            "as a critical alert (16.7% SHAP impact). The affected asset should be inspected immediately for "
            "cooling system integrity, fan operation, and coolant level. In Colombo's wet lowland climate, "
            "thermal stress is elevated due to high ambient humidity and temperature. Assets with coolant "
            "temp readings >95°C must be removed from heavy-load operations until inspected."
        ),
    },
    {
        "title": "Brake Health — Safety-Critical Component",
        "category": "Safety",
        "tags": ["brake", "safety", "critical", "ground", "health"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Brake health is the third-highest SHAP failure driver at 16.4% impact. "
            "Any asset with brake health below 40% must be immediately removed from operations per "
            "ISO 55000 §8.6 safety-critical component protocol. Brake failure is the leading cause of "
            "warehouse injury incidents globally. Assets in the 40-60% brake health range should be "
            "scheduled for service within 7 days. Assets with brake health >80% are within safe operating range."
        ),
    },
    {
        "title": "Days Since Last Service — Calendar PM Trigger",
        "category": "Operations",
        "tags": ["calendar", "service", "days", "pm", "schedule", "overdue"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Days since last service (13.4% SHAP impact) is a calendar-based PM trigger per SMRP BP 3.1. "
            "Any asset exceeding 90 days without service is classified as overdue regardless of engine hours. "
            "For delivery vans (60-day interval), overdue threshold is 60 days. "
            "Cross-referencing engine hours against calendar days catches both usage-intensive and "
            "low-use assets that may have deteriorated without triggering hour-based alerts."
        ),
    },
    {
        "title": "Tire Health — Load-Bearing Component",
        "category": "Maintenance",
        "tags": ["tire", "tyre", "health", "critical", "load", "replacement"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Tire health below 35% is classified as critical (12.9% SHAP impact). "
            "All assets below this threshold require immediate tire replacement. "
            "For heavy trucks (16T) and medium trucks (7T), tire health degradation accelerates under "
            "maximum load conditions. The KB recommends proactive tire assessment at the 50% mark "
            "to schedule replacements before the critical threshold is reached."
        ),
    },
    {
        "title": "Battery Health — Electric Forklift Lifecycle",
        "category": "Troubleshooting",
        "tags": ["battery", "electric", "forklift", "health", "swap", "lifecycle"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Battery health below 40% triggers mandatory swap per SMRP BP 4.3 (9.8% SHAP impact). "
            "Electric forklifts (Forklift 2.5T and 3.0T classes) are the primary affected asset type. "
            "Battery health degradation accelerates in high-temperature environments like Colombo. "
            "The KB recommends battery health monitoring at weekly intervals for electric forklifts "
            "and replacement scheduling when health falls below 50% to avoid critical-threshold failures."
        ),
    },
    {
        "title": "Hydraulic Health — Fluid System Integrity",
        "category": "Troubleshooting",
        "tags": ["hydraulic", "fluid", "seal", "forklift", "health", "inspect"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Hydraulic health below 45% requires immediate inspection per ISO 55000 §8.6 (9.0% SHAP impact). "
            "Recommended action: hydraulic oil flush + seal check on high-use forklifts. "
            "Hydraulic system failures in warehouse forklifts are a primary cause of load-drop incidents. "
            "The 45% threshold triggers inspection; the 30% threshold triggers immediate grounding. "
            "Mechanical tickets correlate strongly with hydraulic health degradation."
        ),
    },
    {
        "title": "Active Fault Code Count — ECU Diagnostics",
        "category": "Troubleshooting",
        "tags": ["fault", "code", "ecu", "obd", "electrical", "software"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "Any active ECU fault code count >0 triggers investigation per SMRP BP 2.1 (4.8% SHAP impact). "
            "All active OBD fault codes must be cleared and investigated immediately. "
            "Unresolved fault codes are primary drivers of electrical ticket volumes. "
            "The KB recommends weekly fault code sweeps for all assets with active fault codes, "
            "particularly for software and electrical ticket categories."
        ),
    },
    {
        "title": "Ticket Priority Thresholds — Escalation Policy",
        "category": "Policies",
        "tags": ["ticket", "priority", "high", "threshold", "escalation", "kb"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "KB warning threshold: ≤40% of open tickets should be classified High-priority. "
            "Exceeding this threshold indicates systemic fault escalation and elevated fleet-level failure risk. "
            "High-priority tickets should be triaged within 24 hours of creation. "
            "When high-priority tickets exceed 40% of open tickets, a fleet-wide safety audit is recommended. "
            "Electrical tickets are particularly important as they correlate with battery health SHAP driver."
        ),
    },
    {
        "title": "Maintenance Cost Model — Critical vs Healthy Assets",
        "category": "Operations",
        "tags": ["cost", "maintenance", "critical", "budget", "financial", "lkr"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "KB cost model: assets in the Below 60% health band incur approximately 2.7x the average "
            "maintenance cost relative to healthy assets (≥80% health). "
            "Rapid remediation of critical assets is therefore a high financial return priority. "
            "Total predicted maintenance cost should be compared against actual 3-month spend to identify "
            "budget variance. Significant underspend may indicate deferred maintenance risk."
        ),
    },
    {
        "title": "Health Score Distribution — Fleet Assessment",
        "category": "Policies",
        "tags": ["health", "score", "distribution", "fleet", "assessment", "band"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
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
        "title": "Recommendations Framework — 3-Tier Urgency",
        "category": "Operations",
        "tags": ["recommendations", "critical", "high", "medium", "urgency", "action"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "KB Recommendations are structured in three urgency tiers: "
            "CRITICAL (0-7 days): immediate safety-critical actions required — ground assets with brake/hydraulic below threshold, "
            "dispatch maintenance for high-priority tickets, extract engine-hour readings for all overdue assets. "
            "HIGH (7-30 days): service all high-risk assets, implement automated monitoring alerts, "
            "execute tyre and battery replacement programs. "
            "MEDIUM (30-90 days): integrate ISO 55000 review cycles, build SHAP-triggered predictive work orders, "
            "expand KB with OEM vehicle-specific service bulletins."
        ),
    },
    {
        "title": "LankaLogix Colombo — Warehouse Context",
        "category": "General",
        "tags": ["lankalogix", "colombo", "warehouse", "context", "climate", "fleet"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": (
            "LankaLogix Colombo warehouse (WH001) operates in a wet lowland climate at Biyagama Road, Kelaniya. "
            "Fleet comprises 7 asset types: Forklift 2.5T (223), Delivery Van 1.5T (218), Light Truck 3.5T (168), "
            "Mini Truck 1T (131), Forklift 3.0T (126), Medium Truck 7T (102), Heavy Truck 16T (32). "
            "Departments: Transportation (TRN), Electrical (ELC), Software (SFT), Mechanical (MEC), Admin (ADM). "
            "High humidity in Colombo accelerates battery degradation and coolant system corrosion, "
            "making these SHAP features particularly critical for this location."
        ),
    },
    {
        "title": "Statutory Lifting-Equipment Inspection Regulations",
        "category": "Safety",
        "tags": ["legal", "compliance", "statutory", "forklift", "lifting", "inspection", "factories ordinance"],
        "source": "Sri Lanka Factories Ordinance No. 45 of 1942, ss. 27–29",
        "content": (
            "Under Sri Lanka Factories Ordinance No. 45 of 1942, lifting equipment requires mandatory examinations: "
            "- Hoists and lifts (Section 27): Thoroughly examined by a competent person every 12 months, recorded within 14 days.\n"
            "- Chains, ropes, and lifting tackle (Section 28): Inspected every 6 months. Annealing required every 14 months (6 months for molten-metal tackle or <=1/2 inch).\n"
            "- Lifting-machine parts and gear (Section 29, includes forklift masts, hooks, anchoring): Examined by a competent person every 14 months.\n"
            "Non-compliance results in automatic grounding of lifting assets until examination is complete."
        ),
    },
    {
        "title": "Guarding & SWL Compliance Standards",
        "category": "Safety",
        "tags": ["legal", "compliance", "safety", "guarding", "safe working load"],
        "source": "Sri Lanka Factories Ordinance No. 45 of 1942, ss. 16–28",
        "content": (
            "All dangerous parts of warehouse machinery and transmission machinery must be securely fenced and guarded. "
            "No lifting equipment or tackle may be loaded beyond its marked Safe Working Load (SWL). "
            "New lifting tackle must undergo load testing and certification before first use. "
            "Under-threshold brake health (<40%) or uncertified SWL requires immediate asset removal from operational duty."
        ),
    },
    {
        "title": "Toyota Forklift Periodic Maintenance OEM Schedule",
        "category": "Maintenance",
        "tags": ["oem", "forklift", "toyota", "service", "engine hours"],
        "source": "Toyota 7FG/7FD Repair Manual (Sept 2000)",
        "content": (
            "Toyota forklift OEM maintenance tiers: "
            "- Daily (8 hrs): Operator inspection of brakes, tyres, controls, fluid leaks.\n"
            "- Weekly (40 hrs): Fluid levels, battery, mast operations.\n"
            "- Monthly (170 hrs): Filters, lubrication, electrical systems.\n"
            "- 3-Monthly (500 hrs): Major service including engine tuning, hydraulics, and primary brake checks.\n"
            "- 6-Monthly (1000 hrs) & Annual (2000 hrs): Deep parts inspection and lubricant overhaul."
        ),
    },
    {
        "title": "Tata PRIMA Truck OEM Service Tiers",
        "category": "Maintenance",
        "tags": ["oem", "truck", "tata", "service", "engine hours"],
        "source": "Tata Motors Service Circular SC/2019/56",
        "content": (
            "Tata Motors service triggers are hourly or calendar-based: "
            "- Pre-trip check (Daily): Brake verification, air-filter-clogging check.\n"
            "- 1st Service (500 hrs / 365 days): First scheduled check.\n"
            "- 2nd Service (1000 hrs / 730 days): Drivetrain, tyre rotation, alignment.\n"
            "- 3rd Service (2000 hrs / 1095 days): Major mechanical overhaul.\n"
            "Ongoing maintenance should be performed at least annually or every 1000 hours, whichever comes first."
        ),
    },
    {
        "title": "FMEA Criticality & Risk Prioritisation Framework",
        "category": "Troubleshooting",
        "tags": ["fmea", "criticality", "prioritisation", "risk", "shap"],
        "source": "ABS FMEA Guidance Notes (May 2015)",
        "content": (
            "FMEA/FMECA prioritises failures by calculating a Criticality Score: Consequence Severity x Occurrence Probability. "
            "PredictiX maps SHAP failure probability (Occurrence) to the asset component role (Consequence Severity) to order "
            "the maintenance queue. Safety-critical components (brakes, steering) carry the highest consequence severity (9/10), "
            "whereas battery/tire degradation represents moderate severity but high occurrence."
        ),
    },
    {
        "title": "ISO 55001 Strategic Asset Management Plan (SAMP)",
        "category": "Policies",
        "tags": ["iso55001", "asset management", "governance", "risk-based"],
        "source": "CEDR Implementation Guide for an ISO 55001 Asset Management System (Oct 2016)",
        "content": (
            "ISO 55001 governs asset lifecycle optimization. It requires a Strategic Asset Management Plan (SAMP) "
            "to convert corporate objectives into risk-based operational maintenance targets under a Plan-Do-Check-Act (PDCA) loop. "
            "Critical-rate, PM-ratio, and SHAP diagnostics must feed regular leadership review cycles to assure governance."
        ),
    },
    {
        "title": "Lifecycle Costing & Deferred Maintenance Risks",
        "category": "Policies",
        "tags": ["iso55001", "cost", "lifecycle", "budget"],
        "source": "CEDR Implementation Guide for an ISO 55001 Asset Management System (Oct 2016)",
        "content": (
            "Asset decisions must evaluate whole Lifecycle Cost (LCC): acquisition, operation, maintenance, and disposal. "
            "Corrective spending on critical assets exceeding 2.7x standard maintenance implies replacement triggers. "
            "Planned maintenance underspend indicates deferred lifecycle risk and must be surfaced as an liability, not a saving."
        ),
    },
    {
        "title": "Colombo Lowland Port Climate Adaptation Guidelines",
        "category": "General",
        "tags": ["colombo", "climate", "temperature", "corrosion", "battery"],
        "source": "Colombo Port (WCT-1) Climate Vulnerability & Adaptation Plan (March 2023)",
        "content": (
            "Colombo's tropical climate features extreme humidity and thermal stress. Adaptation measures for ground fleets include: "
            "- Increasing weekly cooling system and coolant checks due to ambient heat (>95°C critical limit).\n"
            "- Accelerated weekly diagnostics of electric forklift batteries due to temperature-driven degradation.\n"
            "- Corrosion prevention checks on brake systems and undercarriages during monsoon periods."
        ),
    },
    {
        "title": "Three-Layer Maintenance Compliance Framework",
        "category": "Policies",
        "tags": ["compliance", "legal", "oem", "predictive"],
        "source": "PredictiX Compliance Standard",
        "content": (
            "PredictiX assets must comply with three overlapping service layers: "
            "1. Statutory Layer: Factories Ordinance (annual hoists, 6-month tackle, 14-month machine examinations).\n"
            "2. OEM Layer: Manufacturer intervals (Toyota: 500h, Tata: 1000h, Vans: 60 days).\n"
            "3. Predictive Layer: ISO 55000/SMRP targets (<5% critical, >=90% PM ratio).\n"
            "The strictest applicable interval across these three layers governs the asset scheduling queue."
        ),
    }
]


def seed_database():
    log.info("Starting seeding of PredictiX knowledge base articles...")
    
    # 1. Generate text chunks from structural maps to enrich the KB articles
    # SHAP map chunk
    shap_text = "SHAP Feature Thresholds and Action Guidelines:\n"
    for feature, details in SHAP_KB_MAP.items():
        shap_text += f"- {feature.replace('_', ' ').title()}: Threshold: {details['kb_threshold']}. Action: {details['action']} ({details['standard']}).\n"
    KB_DOCUMENTS.append({
        "title": "PredictiX SHAP Failure Driver Thresholds & Actions",
        "category": "Troubleshooting",
        "tags": ["shap", "threshold", "action", "guideline"],
        "source": "PredictiX_KB_Enhanced_Warehouse_Report",
        "content": shap_text
    })

    db = SessionLocal()
    try:
        # Pre-clearing table using direct connection
        log.info("Clearing existing records in knowledge_base table...")
        db.execute(text("DELETE FROM knowledge_base;"))
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("Could not pre-clear table: %s", e)

    # 2. Iterate and seed documents with embeddings
    success_count = 0
    for doc in KB_DOCUMENTS:
        title = doc["title"]
        content = doc["content"]
        category = doc["category"]
        tags = doc["tags"]
        source = doc["source"]

        log.info("Embedding article: %s", title)
        embedding = None
        
        # Retry logic for HuggingFace model loading/rate limit
        for attempt in range(5):
            try:
                embedding = embed_text(f"{title}. {content}")
                break
            except Exception as e:
                log.warning("Embedding attempt %d failed for '%s': %s", attempt + 1, title, e)
                time.sleep(2 ** attempt)

        # Directly insert using SQLAlchemy connection to bypass Supabase RLS
        try:
            db.execute(
                text("""
                    INSERT INTO knowledge_base (title, content, category, source, tags, is_active, embedding)
                    VALUES (:title, :content, :category, :source, :tags, :is_active, :embedding)
                """),
                {
                    "title": title,
                    "content": content,
                    "category": category,
                    "source": source,
                    "tags": tags,
                    "is_active": True,
                    "embedding": str(embedding) if embedding else None
                }
            )
            db.commit()
            success_count += 1
            log.info("Successfully seeded: %s", title)
        except Exception as e:
            db.rollback()
            log.error("Failed to insert article '%s': %s", title, e)

    log.info("Seeding complete! %d articles successfully uploaded via direct DB connection.", success_count)
    db.close()


if __name__ == "__main__":
    seed_database()
