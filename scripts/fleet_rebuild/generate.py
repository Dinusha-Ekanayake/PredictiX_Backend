"""Orchestrates a full fleet generation into in-memory tables + CSV evidence.

Writes nothing to the database. Personnel rows carry placeholder UUIDs; the
loader swaps them for the real ``auth.users`` ids once the accounts exist, so
the whole dataset can be generated and reviewed before anything destructive
happens.
"""

from __future__ import annotations

import csv
import json
import random
import uuid
from datetime import date, datetime
from pathlib import Path

from . import config as C
from . import fleet, operations, people, sensors
from .trajectories import TrajectorySource


def _dept_lookup(departments: list[dict]) -> dict[tuple[str, str], str]:
    return {(d["_warehouse_short"], d["_dept_key"]): d["id"] for d in departments}


def generate(today: date | None = None, seed: int = C.RANDOM_SEED) -> dict[str, list[dict]]:
    today = today or date.today()
    rng = random.Random(seed)
    source = TrajectorySource(seed=seed)

    warehouses = fleet.build_warehouses()
    departments = fleet.build_departments()
    dept_id = _dept_lookup(departments)

    assets, trajectories = fleet.build_fleet(source, today, rng)
    # Vehicles are Logistics assets, that is the department that operates them.
    for a in assets:
        a["department_id"] = dept_id[(a["_warehouse_short"], "LOG")]

    # ── Personnel (placeholder ids, remapped at load) ─────────────────────────
    roster = people.build_roster(rng)
    for p in roster:
        p["id"] = str(uuid.uuid4())
        p["warehouse_id"] = (
            next(w["id"] for w in C.WAREHOUSES if w["short"] == p["warehouse_short"])
            if p["warehouse_short"] else None
        )
        p["department_id"] = (
            dept_id[(p["warehouse_short"], p["dept_key"])] if p["dept_key"] else None
        )

    staff_by_wh_dept: dict[tuple[str, str], list[dict]] = {}
    admins_by_wh: dict[str, list[dict]] = {}
    for p in roster:
        if p["role"] == "super_admin" or p["status"] != "active":
            continue
        if p["role"] == "admin":
            admins_by_wh.setdefault(p["warehouse_short"], []).append(p)
        else:
            staff_by_wh_dept.setdefault((p["warehouse_short"], p["dept_key"]), []).append(p)

    # ── Operations ───────────────────────────────────────────────────────────
    assignments, current_assignment = operations.build_assignments(
        assets, staff_by_wh_dept, admins_by_wh, today, rng
    )
    for a in assets:
        a["assigned_to"] = current_assignment.get(a["id"])
        creators = admins_by_wh.get(a["_warehouse_short"], [])
        a["created_by"] = rng.choice(creators)["id"] if creators else None

    sensor_rows: list[dict] = []
    maintenance_rows: list[dict] = []
    for a in assets:
        traj = trajectories[a["id"]]
        sensor_rows.extend(sensors.build_sensor_readings(a["id"], traj, rng))
        techs = staff_by_wh_dept.get((a["_warehouse_short"], "MECH"), [])
        for ev in sensors.build_maintenance_events(a, traj, rng):
            ev["performed_by"] = rng.choice(techs)["id"] if techs else None
            maintenance_rows.append(ev)

    tickets, comments, history = operations.build_tickets(
        assets, trajectories, staff_by_wh_dept, today, rng
    )
    notifications = operations.build_notifications(
        assets, tickets, current_assignment, admins_by_wh, today, rng
    )

    return {
        "warehouses": warehouses,
        "departments": departments,
        "profiles": roster,
        "assets": assets,
        "sensor_readings": sensor_rows,
        "maintenance_events": maintenance_rows,
        "asset_assignments": assignments,
        "tickets": tickets,
        "ticket_comments": comments,
        "ticket_status_history": history,
        "notifications": notifications,
    }


# ── CSV evidence ──────────────────────────────────────────────────────────────
def _serialise(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if v is None:
        return ""
    return v


def write_csvs(tables: dict[str, list[dict]], out_dir: str = C.OUT_DIR) -> Path:
    """Write one CSV per table as the record of exactly what was generated.

    Internal helper keys (leading underscore) are dropped, and passwords are
    never written, the roster CSV is a personnel record, not a credential dump.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        path = out / f"{name}.csv"
        if not rows:
            path.write_text("", encoding="utf-8")
            continue
        cols = [c for c in rows[0] if not c.startswith("_") and c != "password"]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: _serialise(r.get(c)) for c in cols})
    return out
