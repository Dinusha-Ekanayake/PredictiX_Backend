"""Sensor readings and the maintenance history implied by them.

Maintenance events are *derived from* the trajectories rather than generated
alongside them. Every service in v11 shows up as a step in
``lifetime_service_count`` with ``days_since_last_service`` resetting to a small
number and the serviced component's health jumping back up. Reading the events
back out of that signal guarantees the workshop history and the sensor history
can never contradict each other — which they would if both were rolled
independently.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

# v11 sensor columns that map 1:1 onto sensor_readings columns of the same name.
V11_SENSOR_COLS = [
    "odometer_km", "engine_hours_total", "distance_last_30d_km",
    "operating_hours_last_30d", "idle_hours_last_30d", "trip_count_30d",
    "avg_trip_distance_km", "avg_payload_kg", "payload_utilization_pct",
    "overload_events_30d", "start_stop_burden_30d", "rough_road_pct",
    "urban_route_pct", "port_route_pct", "route_type", "cargo_type",
    "operating_shift", "ambient_temp_avg_c", "ambient_humidity_avg_pct",
    "rainfall_mm_30d", "fuel_price_lkr_per_l", "engine_temp_avg_c",
    "coolant_temp_max_c", "vibration_rms_mm_s", "tire_pressure_psi",
    "fuel_rate_lph", "fuel_efficiency_km_per_l", "battery_voltage_v",
    "oil_life_pct", "brake_health_pct", "tire_health_pct", "battery_health_pct",
    "hydraulic_health_pct", "days_since_last_service",
    "mileage_since_last_service_km", "engine_hours_since_last_service",
    "last_service_type", "maintenance_cost_last_service_lkr",
    "parts_replaced_last_service", "major_component_replaced",
    "active_fault_code_count", "downtime_hours_last_90d",
]

INT_COLS = {"trip_count_30d", "overload_events_30d", "start_stop_burden_30d",
            "days_since_last_service", "active_fault_code_count"}

# Legacy generic columns kept in step with their v11 equivalents. This mirrors
# the convention already in the database: temperature/vibration/humidity/
# voltage/odometer were populated, while pressure/rpm/fuel_level were left NULL
# because no such measurement exists in the dataset. Inventing values for them
# would be fabricating sensor data, so they stay NULL.
LEGACY_MIRROR = {
    "temperature": "engine_temp_avg_c",
    "vibration":   "vibration_rms_mm_s",
    "humidity":    "ambient_humidity_avg_pct",
    "voltage":     "battery_voltage_v",
    "odometer":    "odometer_km",
}

# v11 service type -> maintenance_event_type enum.
SERVICE_EVENT_TYPE = {
    "oil_service":       "scheduled_service",
    "brake_service":     "replacement",
    "tire_service":      "replacement",
    "battery_service":   "replacement",
    "hydraulic_service": "repair",
    "cooling_service":   "repair",
    "engine_service":    "repair",
    "major_overhaul":    "replacement",
}

SERVICE_TITLE = {
    "oil_service":       "Engine oil and filter service",
    "brake_service":     "Brake pad and disc replacement",
    "tire_service":      "Tyre replacement and wheel alignment",
    "battery_service":   "Battery replacement and charging system check",
    "hydraulic_service": "Hydraulic system service",
    "cooling_service":   "Cooling system service",
    "engine_service":    "Engine service",
    "major_overhaul":    "Major overhaul",
}

TYPICAL_DOWNTIME_H = {
    "oil_service": (1.5, 4.0), "brake_service": (3.0, 8.0),
    "tire_service": (2.0, 5.0), "battery_service": (1.0, 3.0),
    "hydraulic_service": (4.0, 12.0), "cooling_service": (3.0, 9.0),
    "engine_service": (8.0, 24.0), "major_overhaul": (48.0, 120.0),
}

# Sri Lankan commercial-vehicle service providers, grouped by the
# service_provider_type v11 already assigns to each vehicle.
VENDORS = {
    "OEM_dealer": [
        "Toyota Lanka (Pvt) Ltd - Service Division",
        "DIMO Truck & Bus Service Centre",
        "United Motors Lanka - Commercial Service",
        "Associated Motorways (AMW) Service",
    ],
    "authorized_workshop": [
        "Sathosa Motors Authorised Workshop",
        "Ideal Motors Commercial Service",
        "Lanka Diesel Services (Pvt) Ltd",
        "Colonial Motors Authorised Service",
    ],
    "independent_garage": [
        "Nawaloka Auto Engineering",
        "Ceylon Fleet Care Garage",
        "Perera Auto Works",
        "Southern Diesel Garage",
    ],
}


def _as_utc(d: date, rng: random.Random) -> datetime:
    """Give a date a plausible working-hours timestamp (Asia/Colombo is UTC+5:30,
    so an 06:00-16:00 UTC window lands inside a local working day)."""
    return datetime.combine(
        d, time(hour=rng.randint(6, 15), minute=rng.randint(0, 59)), tzinfo=timezone.utc
    )


def build_sensor_readings(
    asset_id: str, traj: pd.DataFrame, rng: random.Random
) -> list[dict]:
    rows = []
    for _, r in traj.iterrows():
        row: dict = {
            "asset_id": asset_id,
            "recorded_at": _as_utc(r["snapshot_date"].date(), rng),
            "reading_payload": {},
        }
        for c in V11_SENSOR_COLS:
            v = r[c]
            if isinstance(v, str):
                row[c] = v
            elif c in INT_COLS:
                row[c] = int(v)
            else:
                row[c] = round(float(v), 3)
        # Booleans in the DB, 0/1 integers in v11.
        row["is_home_warehouse_service"] = bool(int(r["is_home_warehouse_service"]))
        row["sensor_fault_flag"] = bool(int(r["sensor_fault_flag"]))
        for legacy, src in LEGACY_MIRROR.items():
            row[legacy] = round(float(r[src]), 3)
        rows.append(row)
    return rows


def build_maintenance_events(
    asset: dict, traj: pd.DataFrame, rng: random.Random
) -> list[dict]:
    """Recover the workshop history from service/breakdown steps in the trajectory."""
    events: list[dict] = []
    provider = asset["service_provider_type"]
    vendors = VENDORS.get(provider, VENDORS["independent_garage"])

    prev = None
    for _, r in traj.iterrows():
        if prev is not None:
            svc_step = int(r["lifetime_service_count"]) - int(prev["lifetime_service_count"])
            brk_step = int(r["lifetime_breakdown_count"]) - int(prev["lifetime_breakdown_count"])

            if svc_step > 0:
                # days_since_last_service has just reset, so it dates the service.
                performed = r["snapshot_date"].date() - timedelta(
                    days=int(r["days_since_last_service"])
                )
                stype = str(r["last_service_type"])
                lo, hi = TYPICAL_DOWNTIME_H.get(stype, (2.0, 6.0))
                parts = str(r["parts_replaced_last_service"])
                events.append({
                    "id": str(uuid.uuid4()),
                    "asset_id": asset["id"],
                    "event_type": SERVICE_EVENT_TYPE.get(stype, "other"),
                    "title": SERVICE_TITLE.get(stype, stype.replace("_", " ").title()),
                    "description": (
                        f"{SERVICE_TITLE.get(stype, stype)} carried out on "
                        f"{asset['make_model']} ({asset['registration_number']}) at "
                        f"{int(r['odometer_km']):,} km."
                    ),
                    "performed_by": None,          # filled in once staff exist
                    "scheduled_date": _as_utc(performed - timedelta(days=rng.randint(1, 7)), rng),
                    "performed_at": _as_utc(performed, rng),
                    "odometer_reading": float(r["odometer_km"]),
                    "downtime_hours": round(rng.uniform(lo, hi), 2),
                    "cost_amount": float(r["maintenance_cost_last_service_lkr"]),
                    "currency": "LKR",
                    "vendor_name": rng.choice(vendors),
                    "notes": (
                        None if parts in ("", "none", "nan")
                        else f"Parts replaced: {parts.replace('|', ', ')}."
                    ),
                    "created_at": _as_utc(performed, rng),
                    "updated_at": _as_utc(performed, rng),
                    "metadata": {
                        "service_type": stype,
                        "major_component_replaced": str(r["major_component_replaced"]),
                        "home_warehouse_service": bool(int(r["is_home_warehouse_service"])),
                        "derived_from": "v11_trajectory_service_step",
                    },
                    "_performed_date": performed,
                })

            if brk_step > 0:
                occurred = r["snapshot_date"].date() - timedelta(days=rng.randint(2, 25))
                events.append({
                    "id": str(uuid.uuid4()),
                    "asset_id": asset["id"],
                    "event_type": "breakdown",
                    "title": "Unplanned breakdown - roadside recovery",
                    "description": (
                        f"{asset['make_model']} ({asset['registration_number']}) was "
                        f"recovered after an unplanned breakdown at "
                        f"{int(r['odometer_km']):,} km."
                    ),
                    "performed_by": None,
                    "scheduled_date": None,        # unplanned by definition
                    "performed_at": _as_utc(occurred, rng),
                    "odometer_reading": float(r["odometer_km"]),
                    "downtime_hours": round(rng.uniform(6.0, 48.0), 2),
                    "cost_amount": round(float(r["maintenance_cost_last_service_lkr"]) * rng.uniform(1.2, 2.1), 2),
                    "currency": "LKR",
                    "vendor_name": rng.choice(vendors),
                    "notes": "Recovered to workshop; vehicle off-road pending repair.",
                    "created_at": _as_utc(occurred, rng),
                    "updated_at": _as_utc(occurred, rng),
                    "metadata": {"derived_from": "v11_trajectory_breakdown_step"},
                    "_performed_date": occurred,
                })
        prev = r

    return events
