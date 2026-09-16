"""Warehouses, departments and the vehicle fleet itself."""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from . import config as C
from .trajectories import TrajectorySource, derive_manufacture_year

# ── Sri Lankan registration plates ────────────────────────────────────────────
# Modern SL plates read "<province> <class letters>-<4 digits>", e.g.
# "WP LC-4821". The letter series encodes vehicle class: P* for dual-purpose
# vehicles (vans), L* for lorries, with heavier classes further down the series.
PLATE_SERIES = {
    "Delivery_Van_1.5T": ["PB", "PC", "PD", "PE"],
    "Mini_Truck_1T":     ["LA", "LB"],
    "Light_Truck_3.5T":  ["LC", "LD"],
    "Medium_Truck_7T":   ["LE", "LF"],
    "Heavy_Truck_16T":   ["LG", "LH"],
}

# VIN alphabet excludes I, O and Q per ISO 3779 (they are too easily confused
# with 1 and 0).
_VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

# World Manufacturer Identifier-style prefixes, one per make in v11.
_WMI = {
    "Toyota HiAce": "JTF", "Nissan Caravan": "JN1", "KDH Van": "JTG",
    "Tata Ace": "MAT", "Piaggio Porter": "ZAP", "Mahindra Bolero Pickup": "MA1",
    "Isuzu ELF NKR": "JAA", "Mitsubishi Canter": "JLB", "Tata Ultra T.7": "MAU",
    "Isuzu FVR": "JAL", "Mitsubishi Fuso Fighter": "JLF", "Tata T.12": "MAT",
    "Mercedes Actros 1836": "WDB", "Tata Signa 1918": "MAS", "Tata Prima 2823": "MAP",
}
# Forklifts carry a manufacturer serial (PIN), not a road VIN.
_FORKLIFT_SERIAL_PREFIX = {
    "Komatsu FD25": "KMT-FD25", "Komatsu FD30": "KMT-FD30",
    "Toyota 8FD25": "TYT-8FD25", "Toyota 8FD30": "TYT-8FD30",
    "Heli CPCD25": "HLI-CPCD25", "Heli CPCD30": "HLI-CPCD30",
}

PARKING_BAYS_PER_ZONE = 60
_ZONE_LETTERS = "ABCDEFGHJKLMNP"   # I and O skipped, same confusion problem


def _vin(rng: random.Random, make_model: str) -> str:
    prefix = _WMI.get(make_model, "LLX")
    return prefix + "".join(rng.choice(_VIN_ALPHABET) for _ in range(14))


def _forklift_serial(rng: random.Random, make_model: str) -> str:
    prefix = _FORKLIFT_SERIAL_PREFIX.get(make_model, "FLT-GEN")
    return f"{prefix}-{rng.randint(100000, 999999)}"


def _health_band(mean_health: float) -> str:
    """Band a vehicle by the mean of its five component health percentages.

    Thresholds are calibrated against the actual distribution rather than set to
    round numbers. v11's component medians sit near 46-50% because that is what
    mid-service-interval wear looks like, a component at 50% of its life is a
    normal component, not a failing one. Banding it as "poor" (which naive
    80/65/45/25 cut-offs do) would paint half a healthy fleet red.

    These cut-offs yield roughly 2% excellent / 28% good / 52% moderate /
    16% poor / 3% critical across the generated fleet: most vehicles mid-life, a
    real minority needing attention, a small critical tail.

    Note this is a coarse rollup for list filtering and the health-distribution
    chart. It is deliberately *not* the PdM signal, component-level risk comes
    from the survival models and the tier from pdm_decision_service, both of
    which can flag a vehicle whose average looks unremarkable.
    """
    if mean_health >= 70:
        return "excellent"
    if mean_health >= 52:
        return "good"
    if mean_health >= 36:
        return "moderate"
    if mean_health >= 25:
        return "poor"
    return "critical"


def _criticality(priority: str, rng: random.Random) -> float:
    span = {"critical": (82, 96), "high": (63, 81), "medium": (38, 62)}.get(priority, (38, 62))
    return round(rng.uniform(*span), 2)


def build_warehouses() -> list[dict]:
    rows = []
    for w in C.WAREHOUSES:
        rows.append({
            "id": w["id"], "code": w["code"], "name": w["name"],
            "address": w["address"], "city": w["city"], "district": w["district"],
            "country": "Sri Lanka", "timezone": "Asia/Colombo", "is_active": True,
            "climate_zone": w["climate_zone"], "warehouse_type": w["warehouse_type"],
            "metadata": {
                "short_code": w["short"],
                "plate_province": w["plate_province"],
                "planned_fleet_size": w["fleet_size"],
                "dataset_source": C.V11_CSV.rsplit("/", 1)[-1],
            },
        })
    return rows


def build_departments() -> list[dict]:
    rows = []
    for w in C.WAREHOUSES:
        for d in C.DEPARTMENTS:
            rows.append({
                "id": str(uuid.uuid4()),
                "warehouse_id": w["id"],
                "code": f"{w['short']}-{d['code']}",
                "name": d["name"],
                "description": f"{d['description']} — {w['name']}",
                "is_active": True,
                "_dept_key": d["code"],
                "_warehouse_short": w["short"],
            })
    return rows


def build_fleet(
    source: TrajectorySource,
    today: date,
    rng: random.Random,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:
    """Select trajectories and derive one asset row per vehicle.

    Returns ``(asset_rows, {asset_id: conditioned_trajectory})``, the
    trajectories are handed on to the sensor-reading builder so both are
    guaranteed to describe the same vehicle history.
    """
    pool = source.vehicles_by_type()
    for vt in pool:
        rng.shuffle(pool[vt])
    cursor = {vt: 0 for vt in pool}

    assets: list[dict] = []
    trajectories: dict[str, pd.DataFrame] = {}

    for w_idx, w in enumerate(C.WAREHOUSES):
        short, province = w["short"], w["plate_province"]
        # Group by vehicle_type first so similar vehicles share a parking zone,
        # which is how a real yard is laid out.
        picks: list[tuple[str, str]] = []
        for vt, counts in C.FLEET_MIX.items():
            n = counts[w_idx]
            available = pool[vt][cursor[vt]: cursor[vt] + n]
            if len(available) < n:
                raise RuntimeError(
                    f"v11 has too few {vt} vehicles left for {short}: "
                    f"need {n}, have {len(available)}"
                )
            cursor[vt] += n
            picks.extend((vt, vid) for vid in available)

        for seq, (vt, vid) in enumerate(picks, start=1):
            traj = source.take(vid, short, today)
            last = traj.iloc[-1]
            asset_id = str(uuid.uuid4())

            make_model = str(last["make_model"])
            make, _, model = make_model.partition(" ")
            is_forklift = vt in C.FORKLIFT_TYPES

            if is_forklift:
                # Internal plant equipment: fleet/unit number, no road plate.
                registration = f"{short}-FL-{seq:03d}"
                vin = _forklift_serial(rng, make_model)
            else:
                series = rng.choice(PLATE_SERIES[vt])
                registration = f"{province} {series}-{rng.randint(1000, 9999)}"
                vin = _vin(rng, make_model)

            zone = _ZONE_LETTERS[(seq - 1) // PARKING_BAYS_PER_ZONE]
            bay = (seq - 1) % PARKING_BAYS_PER_ZONE + 1
            parking_slot = f"{zone}-{bay:03d}"

            mfg_year = derive_manufacture_year(last["vehicle_age_years"], today)
            purchase = date(mfg_year, rng.randint(1, 12), rng.randint(1, 28))
            # 3-year commercial vehicle warranty is the norm for SL fleet buys.
            warranty_expiry = date(purchase.year + 3, purchase.month, purchase.day)

            health_cols = ["oil_life_pct", "brake_health_pct", "tire_health_pct",
                           "battery_health_pct", "hydraulic_health_pct"]
            mean_health = float(sum(float(last[c]) for c in health_cols) / len(health_cols))

            last_service = today - timedelta(days=int(last["days_since_last_service"]))
            next_service = today + timedelta(days=int(round(float(last["days_until_next_maintenance"]))))

            # Status follows the vehicle's actual condition rather than a
            # random draw: a vehicle already flagged for maintenance inside 30
            # days and sitting on very low component health is genuinely in the
            # workshop, not out on the road.
            if mean_health < 22 and int(last["maintenance_required_next_30d"]) == 1:
                status = "under_maintenance"
            elif mean_health < 30 and rng.random() < 0.35:
                status = "under_maintenance"
            elif rng.random() < 0.025:
                status = "inactive"
            else:
                status = "active"

            assets.append({
                "id": asset_id,
                "asset_code": f"LLX-{short}-{seq:04d}",
                "warehouse_id": w["id"],
                "department_id": None,          # filled in once departments exist
                "asset_name": f"{make_model} {seq:03d}",
                "asset_type": "vehicle",
                "category": "forklift" if is_forklift else "road_vehicle",
                "vehicle_type": vt,
                "make": make,
                "model": model or make_model,
                "manufacture_year": mfg_year,
                "registration_number": registration,
                "vin": vin,
                "parking_slot": parking_slot,
                "status": status,
                "health_band": _health_band(mean_health),
                "criticality_score": _criticality(str(last["maintenance_priority"]), rng),
                "purchase_date": purchase,
                "warranty_expiry_date": warranty_expiry,
                "assigned_to": None,            # filled in by the assignment builder
                "current_mileage": float(last["odometer_km"]),
                "last_service_date": last_service,
                "next_service_date": next_service,
                "description": (
                    f"{make_model} ({vt.replace('_', ' ')}) operating out of {w['name']} "
                    f"on {str(last['vehicle_role']).replace('_', ' ')} duty."
                ),
                "vehicle_role": str(last["vehicle_role"]),
                "make_model": make_model,
                "fuel_type": str(last["fuel_type"]),
                "transmission": str(last["transmission"]),
                "service_provider_type": str(last["service_provider_type"]),
                "payload_capacity_kg": float(last["payload_capacity_kg"]),
                "maintenance_priority": str(last["maintenance_priority"]),
                "vehicle_age_years": int(round(float(last["vehicle_age_years"]))),
                "lifetime_service_count": int(last["lifetime_service_count"]),
                "lifetime_breakdown_count": int(last["lifetime_breakdown_count"]),
                # Explicit rather than left to the now() default: an asset
                # record is created when the vehicle enters the fleet, and
                # dating all 850 to today would make every "assets added over
                # time" chart a single spike.
                "created_at": datetime.combine(purchase, time(9, 0), tzinfo=timezone.utc),
                "updated_at": datetime.combine(today, time(9, 0), tzinfo=timezone.utc),
                "metadata": {
                    "source_vehicle_id": vid,
                    "warehouse_short": short,
                    "operating_shift": str(last["operating_shift"]),
                    "route_type": str(last["route_type"]),
                    "cargo_type": str(last["cargo_type"]),
                },
                "_warehouse_short": short,
            })
            trajectories[asset_id] = traj

    return assets, trajectories
