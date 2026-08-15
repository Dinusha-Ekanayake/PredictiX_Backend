"""Tunables for the LankaLogix fleet rebuild.

Everything the generator can be argued about lives here, so the numbers can be
reviewed without reading the generation code.

Design rule that governs this whole package: **nothing is invented that v11
already knows.** The trained models (PdM classifier/regressor v7, cost v5,
survival v3) were all fitted on
``app/ai/dataset/srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv``.
Rather than synthesising 56 sensor columns from guessed distributions — which is
how the previous fleet ended up out of distribution — each new asset adopts a
real per-vehicle trajectory out of v11 and is re-dated to end today. Coherence
(odometer monotonicity, service resets, lifetime counters, health decay) is
therefore inherited, not re-derived.
"""

from __future__ import annotations

# ── Source dataset ────────────────────────────────────────────────────────────
V11_CSV = "app/ai/dataset/srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv"

# 61 monthly snapshots = 5 years of history whose final row is dated "today",
# which is the fix for the defect that motivated this rebuild: the previous
# fleet's newest reading was 139 days stale, so days_since_last_service (the
# #2 model feature) was understated ~4x fleet-wide.
SNAPSHOTS_PER_ASSET = 61

RANDOM_SEED = 20260810

# ── Warehouses ────────────────────────────────────────────────────────────────
# Colombo and Badulla keep their existing UUIDs (verified: no runtime code and
# no frontend file references them, only historical seed_data/*.sql, so this is
# purely to avoid churn). Galle is new.
WAREHOUSES = [
    {
        "id": "c537c281-b6ad-4842-94ec-e937be0083e5",
        "code": "LL-COL",
        "short": "COL",
        "name": "LankaLogix - Colombo",
        "address": "No. 285, Biyagama Road, Kelaniya",
        "city": "Colombo",
        "district": "Colombo",
        "climate_zone": "wet_lowland",
        "warehouse_type": "distribution_hub",
        "plate_province": "WP",          # Western Province
        "fleet_size": 400,
    },
    {
        "id": "23a10ad6-f2ff-4aab-9878-de0f37f6bbe0",
        "code": "LL-BDL",
        "short": "BDL",
        "name": "LankaLogix - Badulla",
        "address": "No. 12, Main Street, Badulla",
        "city": "Badulla",
        "district": "Badulla",
        "climate_zone": "upcountry_intermediate",
        "warehouse_type": "regional_hub",
        "plate_province": "UP",          # Uva Province
        "fleet_size": 200,
    },
    {
        "id": "8f2b1c74-59d3-4a6e-9b21-7c4e0a5d3f88",
        "code": "LL-GLE",
        "short": "GLE",
        "name": "LankaLogix - Galle",
        "address": "No. 47, Wakwella Road, Galle",
        "city": "Galle",
        "district": "Galle",
        "climate_zone": "wet_coastal",
        "warehouse_type": "port_logistics_hub",
        "plate_province": "SP",          # Southern Province
        "fleet_size": 250,
    },
]

# ── Fleet composition ─────────────────────────────────────────────────────────
# Per-warehouse counts by vehicle_type. The 7 types are hard-locked: the
# survival models one-hot vehicle_type/vehicle_role into fixed columns, so an
# unknown value silently collapses to the baseline category (a wrong answer,
# not an error). Column totals are checked against the number of DISTINCT v11
# vehicles of each type (each new asset consumes one, without replacement):
#   Forklift_2.5T 302 | Delivery_Van_1.5T 268 | Light_Truck_3.5T 232
#   Mini_Truck_1T 190 | Forklift_3.0T 186 | Medium_Truck_7T 160
#   Heavy_Truck_16T 51
#
# Mix rationale — Colombo is the mixed distribution hub (van-heavy last-mile);
# Badulla is an upcountry regional hub on hill roads (light/medium truck heavy,
# few forklifts, no port work); Galle is a port logistics hub (forklift-heavy
# container handling, more heavy haulage).
FLEET_MIX = {
    #  vehicle_type            COL  BDL  GLE
    "Forklift_2.5T":         (  88,  30,  55),
    "Forklift_3.0T":         (  52,  16,  40),
    "Delivery_Van_1.5T":     (  96,  40,  45),
    "Mini_Truck_1T":         (  60,  38,  35),
    "Light_Truck_3.5T":      (  64,  50,  45),
    "Medium_Truck_7T":       (  32,  20,  22),
    "Heavy_Truck_16T":       (   8,   6,   8),
}

# Forklifts are internal plant equipment: no road registration. Industry
# practice is a stamped fleet/unit number instead, with the manufacturer serial
# kept separately (we put it in `vin`).
FORKLIFT_TYPES = {"Forklift_2.5T", "Forklift_3.0T"}

# ── Regional environmental conditioning ───────────────────────────────────────
# v11 is a single Colombo warehouse, so warehouse identity itself is NOT a model
# feature (verified against all 58 feature names) — regional character can only
# reach the models through these environmental columns, which ARE features.
#
# Each entry is (multiplier, additive_offset) applied to the Colombo baseline,
# then hard-clipped to v11's own observed [min, max] for that column so no value
# ever lands outside the trained domain.
REGIONAL_ADJUST = {
    "COL": {},  # baseline — v11 is Colombo, left untouched
    "BDL": {    # Uva hill country ~680 m: cooler, drier, rough mountain roads, landlocked
        "ambient_temp_avg_c":       (1.0, -3.5),
        "ambient_humidity_avg_pct":  (1.0, -6.0),
        "rainfall_mm_30d":           (0.85, 0.0),
        # 1.5x, not 2x: at 2x most vehicles pinned to v11's 44.4 ceiling, which
        # made every Badulla vehicle report an identical road-roughness value.
        "rough_road_pct":            (1.50, 0.0),
        "urban_route_pct":           (0.60, 0.0),
        "port_route_pct":            (0.05, 0.0),
    },
    "GLE": {    # southern coastal port: humid, wetter monsoon, heavy port shuttle work
        "ambient_temp_avg_c":       (1.0, -0.5),
        "ambient_humidity_avg_pct":  (1.0, +4.0),
        "rainfall_mm_30d":           (1.15, 0.0),
        "rough_road_pct":            (0.90, 0.0),
        "urban_route_pct":           (0.85, 0.0),
        # Galle is the group's port hub, so port shuttle work is proportionally
        # heavier than Colombo for whichever vehicles already do it.
        "port_route_pct":            (2.20, 0.0),
    },
}

# Columns the clipping above applies to (bounds are read from v11 at runtime).
ENV_COLS = [
    "ambient_temp_avg_c",
    "ambient_humidity_avg_pct",
    "rainfall_mm_30d",
    "rough_road_pct",
    "urban_route_pct",
    "port_route_pct",
]

# ── Departments ───────────────────────────────────────────────────────────────
# Logistics is the rename of the old Transportation department (TRN -> LOG).
# `code` is the DB department code; `acronym` is the email local-part suffix.
DEPARTMENTS = [
    {"code": "LOG",  "acronym": "log",  "name": "Logistics",
     "description": "Fleet operations, drivers and forklift operators"},
    {"code": "ELEC", "acronym": "elec", "name": "Electrical",
     "description": "Vehicle electrical systems, batteries and charging infrastructure"},
    {"code": "SFT",  "acronym": "sft",  "name": "Software",
     "description": "Telematics, sensor integration and platform support"},
    {"code": "MECH", "acronym": "mech", "name": "Mechanical",
     "description": "Engine, brake, tyre and hydraulic maintenance"},
    {"code": "ADM",  "acronym": "adm",  "name": "Admin",
     "description": "Warehouse administration, scheduling and compliance"},
]

# ── Headcount ─────────────────────────────────────────────────────────────────
# Logistics headcount exceeds the fleet size on purpose: vehicles run multiple
# shifts (v11's operating_shift is day / day_night / three_shift), drivers are
# allocated and de-allocated, and one driver may hold several assignments over
# time. ~1.3 drivers per vehicle is the multi-shift norm.
#
# Support headcount is scaled off Colombo's stated establishment rather than
# held flat, because a 200-vehicle depot does not carry the same workshop as a
# 400-vehicle hub. Colombo uses the requested figures exactly; Badulla and Galle
# are pro-rated by fleet size and floored so a small depot still has cover.
HEADCOUNT = {
    #        admins  LOG  MECH  ELEC  SFT  ADM(dept users)
    "COL": {"admin": 10, "LOG": 520, "MECH": 60, "ELEC": 15, "SFT": 8, "ADM": 5},
    "BDL": {"admin":  8, "LOG": 260, "MECH": 30, "ELEC":  8, "SFT": 4, "ADM": 5},
    "GLE": {"admin":  9, "LOG": 325, "MECH": 38, "ELEC": 10, "SFT": 5, "ADM": 5},
}

# ── Accounts ──────────────────────────────────────────────────────────────────
EMAIL_DOMAIN = "lankalogix.com"

SUPER_ADMINS = [
    # Shown on the login screen as the demo super-admin, so it is deliberately
    # generic — the login page should not advertise a real person's address.
    # On the company domain like every other demo account; the gmail addresses
    # below belong to real people.
    {"email": "demosuperadmin@" + EMAIL_DOMAIN, "full_name": "Demo Super Admin"},
    {"email": "dinushatemp@gmail.com",          "full_name": "Dinusha Ekanayake"},
    {"email": "neuromindspredictix@gmail.com",  "full_name": "NeuroMinds PredictiX"},
    {"email": "aroshnimantha386@gmail.com",     "full_name": "Aroshan Nimantha"},
    {"email": "sharadaabeywickrama@gmail.com",  "full_name": "Sharada Abeywickrama"},
    {"email": "tajmibhagya@gmail.com",          "full_name": "Tajmi Bhagya"},
]

PASSWORD_SUPER_ADMIN = "superadmin@123"
PASSWORD_ADMIN       = "admin@123"
PASSWORD_USER        = "user@123"
PASSWORD_DEMO_ADMIN  = "demoadmin@123"
PASSWORD_DEMO_USER   = "demouser@123"

# Per-warehouse demo pair, e.g. demoadmingalle.adm@lankalogix.com /
# demousergalle.adm@lankalogix.com — both sit in the Admin department.
DEMO_ADMIN_TEMPLATE = "demoadmin{city}.adm@" + EMAIL_DOMAIN
DEMO_USER_TEMPLATE  = "demouser{city}.adm@" + EMAIL_DOMAIN

# ── Operational volume ────────────────────────────────────────────────────────
# Tickets are raised off real degradation in the generated trajectories rather
# than sprinkled at random, so the ticket load tracks fleet condition.
TICKETS_PER_100_ASSETS_PER_YEAR = 55
TICKET_HISTORY_YEARS = 2

# Share of vehicles that currently sit with an active driver assignment. The
# remainder are genuinely unassigned (in the yard, between shifts, off-hire) —
# a real state the UI should be able to show.
ACTIVE_ASSIGNMENT_RATE = 0.82

# ── Output ────────────────────────────────────────────────────────────────────
OUT_DIR = "app/warehouse_databases"
