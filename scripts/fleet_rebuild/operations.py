"""Driver assignments, tickets and notifications.

Tickets are raised off real degradation in the generated trajectories — the
component that was actually worn on the day the ticket opens decides the
category, the priority and the wording. Sprinkling random tickets across the
fleet would have produced a helpdesk whose contents contradict the sensor
history the models read.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from . import config as C

# component -> (ticket_category, health column, symptom templates)
COMPONENT_TICKETS = {
    "brake": ("mechanical", "brake_health_pct", [
        ("Brake performance degraded - inspection required",
         "Driver reports longer stopping distance and reduced pedal firmness. Brake wear "
         "indicator is low on condition monitoring. Mechanical team to inspect pads, discs "
         "and brake fluid."),
        ("Brake noise reported during descent",
         "Squealing and vibration reported under braking on gradient. Requesting brake pad "
         "and disc inspection before the vehicle returns to route."),
    ]),
    "tire": ("mechanical", "tire_health_pct", [
        ("Tyre wear beyond service limit",
         "Tread depth is below the service threshold on condition monitoring. Requesting "
         "tyre replacement and wheel alignment check."),
        ("Uneven tyre wear and vibration at speed",
         "Driver reports steering vibration at highway speed. Suspect uneven tyre wear; "
         "requesting inspection, rotation and alignment."),
    ]),
    "battery": ("electrical", "battery_health_pct", [
        ("Battery voltage low - charging system check required",
         "Battery voltage trend is below target and the vehicle is slow to crank in the "
         "morning. Electrical team to test battery health, alternator output and earth "
         "connections."),
        ("Repeated hard starting in early shift",
         "Vehicle requires multiple crank attempts at shift start. Battery state of health "
         "is degraded on monitoring. Requesting battery and charging system diagnosis."),
    ]),
    "oil": ("mechanical", "oil_life_pct", [
        ("Engine oil life exhausted - service overdue",
         "Oil life monitor has reached the end of its interval. Requesting engine oil and "
         "filter service before further dispatch."),
        ("Oil pressure warning intermittent",
         "Intermittent oil pressure warning reported on the instrument cluster. Requesting "
         "oil level, filter and sender inspection."),
    ]),
    "hydraulic": ("mechanical", "hydraulic_health_pct", [
        ("Hydraulic lift slow to respond",
         "Forklift mast raises slowly under load and drifts down when held. Requesting "
         "hydraulic fluid, seal and pump inspection."),
        ("Hydraulic fluid weeping at cylinder",
         "Visible weeping at the lift cylinder and reduced hydraulic performance on "
         "monitoring. Requesting seal replacement."),
    ]),
}

# Telematics faults are a software concern rather than a component wear issue.
SOFTWARE_TICKETS = [
    ("Telematics unit not reporting",
     "Sensor gateway on this vehicle has stopped publishing readings. Software team to "
     "check the telematics unit, SIM connectivity and data pipeline ingestion."),
    ("Fault codes not clearing after service",
     "Active fault codes remain present on the dashboard after the workshop reset. "
     "Requesting diagnostic tool session and ECU log review."),
    ("Odometer readings inconsistent in platform",
     "Reported odometer on the platform disagrees with the vehicle cluster. Software team "
     "to verify sensor mapping and ingestion for this asset."),
]

RESOLUTION_COMMENTS = [
    "Inspected on arrival; confirmed the reported symptom.",
    "Parts ordered from the supplier, awaiting delivery.",
    "Work completed and the vehicle was road tested before release.",
    "Vehicle released back to operations after sign-off.",
    "Handed over to the next shift for completion.",
    "Escalated to the workshop foreman for a second opinion.",
]

PRIORITY_BY_HEALTH = [(12, "high"), (30, "medium")]


def _as_utc(d: date, rng: random.Random) -> datetime:
    return datetime.combine(
        d, time(hour=rng.randint(5, 17), minute=rng.randint(0, 59)), tzinfo=timezone.utc
    )


def _priority(health: float) -> str:
    for threshold, p in PRIORITY_BY_HEALTH:
        if health < threshold:
            return p
    return "low"


def build_assignments(
    assets: list[dict],
    staff_by_wh_dept: dict[tuple[str, str], list[dict]],
    admins_by_wh: dict[str, list[dict]],
    today: date,
    rng: random.Random,
) -> tuple[list[dict], dict[str, str]]:
    """Assign drivers/operators to vehicles.

    Logistics headcount deliberately exceeds the fleet size (multi-shift
    operation), so assignment is driver-major: every vehicle that is currently
    crewed gets one active assignment, and a driver may hold more than one over
    time. Historical, closed-off assignments are included so the vehicle has a
    custody trail rather than appearing to have had one driver forever.
    """
    rows: list[dict] = []
    current: dict[str, str] = {}

    for a in assets:
        short = a["_warehouse_short"]
        drivers = staff_by_wh_dept.get((short, "LOG"), [])
        admins = admins_by_wh.get(short, [])
        if not drivers:
            continue
        assigner = rng.choice(admins)["id"] if admins else None

        # Prior custody: 0-2 closed assignments over the last few years.
        cursor = today - timedelta(days=rng.randint(900, 1700))
        for _ in range(rng.randint(0, 2)):
            holder = rng.choice(drivers)
            start = cursor
            end = start + timedelta(days=rng.randint(120, 500))
            if end >= today:
                break
            rows.append({
                "id": str(uuid.uuid4()), "asset_id": a["id"], "user_id": holder["id"],
                "assigned_by": assigner,
                "assigned_at": _as_utc(start, rng), "unassigned_at": _as_utc(end, rng),
                "is_active": False,
                "notes": "Reassigned during shift roster change.",
            })
            cursor = end + timedelta(days=rng.randint(1, 30))

        # A vehicle in the workshop or off the road is genuinely uncrewed.
        if a["status"] != "active" or rng.random() > C.ACTIVE_ASSIGNMENT_RATE:
            continue
        holder = rng.choice(drivers)
        start = max(cursor, today - timedelta(days=rng.randint(20, 400)))
        rows.append({
            "id": str(uuid.uuid4()), "asset_id": a["id"], "user_id": holder["id"],
            "assigned_by": assigner,
            "assigned_at": _as_utc(start, rng), "unassigned_at": None,
            "is_active": True,
            "notes": None,
        })
        current[a["id"]] = holder["id"]

    return rows, current


def build_tickets(
    assets: list[dict],
    trajectories: dict[str, pd.DataFrame],
    staff_by_wh_dept: dict[tuple[str, str], list[dict]],
    today: date,
    rng: random.Random,
    start_number: int = 1,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (tickets, comments, status_history)."""
    n_tickets = int(
        len(assets) / 100 * C.TICKETS_PER_100_ASSETS_PER_YEAR * C.TICKET_HISTORY_YEARS
    )
    horizon = timedelta(days=int(365 * C.TICKET_HISTORY_YEARS))

    tickets: list[dict] = []
    comments: list[dict] = []
    history: list[dict] = []
    number = start_number

    for _ in range(n_tickets):
        asset = rng.choice(assets)
        short = asset["_warehouse_short"]
        traj = trajectories[asset["id"]]

        # Only look at the window tickets are allowed to fall in.
        window = traj[traj["snapshot_date"] >= pd.Timestamp(today - horizon)]
        if window.empty:
            continue
        snap = window.iloc[rng.randrange(len(window))]
        opened = snap["snapshot_date"].date() + timedelta(days=rng.randint(0, 20))
        if opened >= today:
            opened = today - timedelta(days=rng.randint(1, 5))

        # Software tickets come from telematics faults, everything else from the
        # component that is actually most worn on that day. A baseline share is
        # raised independently of sensor_fault_flag, because platform-side
        # problems (gateway offline, ingestion mismatch, ECU logs) do not
        # require the vehicle itself to be faulty — and v11's sensor_fault_flag
        # is rare enough on its own to leave a staffed Software department with
        # almost no work, which is not a realistic helpdesk.
        software_trigger = (
            bool(int(snap["sensor_fault_flag"])) and rng.random() < 0.55
        ) or rng.random() < 0.09
        if software_trigger:
            category = "software"
            title, description = rng.choice(SOFTWARE_TICKETS)
            priority = rng.choice(["low", "medium", "medium", "high"])
            component = "telematics"
        else:
            component = min(
                COMPONENT_TICKETS,
                key=lambda c: float(snap[COMPONENT_TICKETS[c][1]]),
            )
            category, health_col, templates = COMPONENT_TICKETS[component]
            title, description = rng.choice(templates)
            priority = _priority(float(snap[health_col]))

        reporters = staff_by_wh_dept.get((short, "LOG"), [])
        dept = {"mechanical": "MECH", "electrical": "ELEC", "software": "SFT"}[category]
        handlers = staff_by_wh_dept.get((short, dept), []) or reporters
        if not reporters or not handlers:
            continue
        reporter = rng.choice(reporters)
        handler = rng.choice(handlers)

        age_days = (today - opened).days
        # Older tickets have had time to close; recent ones are still moving.
        if age_days > 120:
            status = rng.choices(["closed", "resolved", "open"], weights=[70, 25, 5])[0]
        elif age_days > 30:
            status = rng.choices(["resolved", "in_progress", "closed", "open"],
                                 weights=[40, 25, 20, 15])[0]
        else:
            status = rng.choices(["open", "in_progress", "resolved"],
                                 weights=[50, 35, 15])[0]

        resolved_at = closed_at = reviewed_at = None
        if status in ("resolved", "closed"):
            resolved_on = opened + timedelta(days=rng.randint(1, min(25, max(2, age_days))))
            resolved_at = _as_utc(resolved_on, rng)
            reviewed_at = resolved_at
            if status == "closed":
                closed_at = _as_utc(
                    resolved_on + timedelta(days=rng.randint(1, 10)), rng
                )

        ticket_id = str(uuid.uuid4())
        vehicle_ref = f"{asset['make_model']} ({asset['registration_number']})"
        tickets.append({
            "id": ticket_id,
            "ticket_number": f"TCK-{number:06d}",
            "asset_id": asset["id"],
            "warehouse_id": asset["warehouse_id"],
            "title": title,
            "description": f"{description}\n\nVehicle: {vehicle_ref}, bay {asset['parking_slot']}.",
            "status": status,
            "priority": priority,
            # The platform's ticket models classify on intake; agreement with the
            # human-confirmed value is high but deliberately not perfect.
            "predicted_priority": priority if rng.random() < 0.86 else rng.choice(["low", "medium", "high"]),
            "final_priority": priority,
            "predicted_category": category if rng.random() < 0.91 else rng.choice(["mechanical", "electrical", "software"]),
            "final_category": category,
            "ticket_summary": f"{component.title()} issue reported on {vehicle_ref}; {category} team engaged.",
            "asset_summary": None,
            "created_by": reporter["id"],
            "assigned_to": handler["id"],
            "reviewed_by": handler["id"] if reviewed_at else None,
            "opened_at": _as_utc(opened, rng),
            "reviewed_at": reviewed_at,
            "resolved_at": resolved_at,
            "closed_at": closed_at,
            # created_at/updated_at must be set explicitly. They default to
            # now(), which for backdated rows makes every time-series that
            # groups on them collapse into today and turns any
            # "resolved_at - created_at" duration negative (observed: an
            # average resolution time of -380 days on the admin dashboard).
            "created_at": _as_utc(opened, rng),
            "updated_at": closed_at or resolved_at or reviewed_at or _as_utc(opened, rng),
            "metadata": {
                "component": component,
                "asset_code": asset["asset_code"],
                "trigger_snapshot": str(snap["snapshot_date"].date()),
            },
        })
        number += 1

        # Status trail.
        prev_status = "open"
        history.append({
            "id": str(uuid.uuid4()), "ticket_id": ticket_id, "old_status": None,
            "new_status": "open", "changed_by": reporter["id"],
            "note": "Ticket raised from the fleet condition report.",
            "created_at": _as_utc(opened, rng),
        })
        for nxt, when in (("in_progress", opened + timedelta(days=1)),
                          ("resolved", resolved_at), ("closed", closed_at)):
            if status == "open":
                break
            if nxt == "in_progress" and status in ("in_progress", "resolved", "closed"):
                history.append({
                    "id": str(uuid.uuid4()), "ticket_id": ticket_id,
                    "old_status": prev_status, "new_status": nxt,
                    "changed_by": handler["id"], "note": "Assigned and work started.",
                    "created_at": _as_utc(min(when, today), rng),
                })
                prev_status = nxt
            elif nxt in ("resolved", "closed") and when is not None and status in ("resolved", "closed"):
                if nxt == "closed" and status != "closed":
                    continue
                history.append({
                    "id": str(uuid.uuid4()), "ticket_id": ticket_id,
                    "old_status": prev_status, "new_status": nxt,
                    "changed_by": handler["id"],
                    "note": "Work completed and verified." if nxt == "resolved" else "Ticket closed.",
                    "created_at": when,
                })
                prev_status = nxt

        for _ in range(rng.randint(0, 3)):
            author = rng.choice([reporter, handler])
            comments.append({
                "id": str(uuid.uuid4()), "ticket_id": ticket_id, "user_id": author["id"],
                "comment": rng.choice(RESOLUTION_COMMENTS),
                "is_internal": author is handler and rng.random() < 0.4,
                "created_at": _as_utc(opened + timedelta(days=rng.randint(0, 12)), rng),
            })

    return tickets, comments, history


def build_notifications(
    assets: list[dict],
    tickets: list[dict],
    current_assignment: dict[str, str],
    admins_by_wh: dict[str, list[dict]],
    today: date,
    rng: random.Random,
) -> list[dict]:
    """In-app notifications for critical assets and ticket activity."""
    rows: list[dict] = []

    def add(user_id, ntype, title, message, when, asset_id=None, ticket_id=None):
        age = (today - when).days
        # Anything more than a few days old has almost certainly been seen.
        read = rng.random() < (0.9 if age > 7 else 0.35)
        rows.append({
            "id": str(uuid.uuid4()), "user_id": user_id, "type": ntype,
            "channel": "in_app", "title": title, "message": message,
            "status": "read" if read else "unread",
            "related_asset_id": asset_id, "related_ticket_id": ticket_id,
            "related_report_id": None,
            "sent_at": _as_utc(when, rng),
            "read_at": _as_utc(when + timedelta(days=rng.randint(0, 3)), rng) if read else None,
            "metadata": {},
            # Explicit for the same reason as tickets: the column defaults to
            # now(), which would date every backdated notification today.
            "created_at": _as_utc(when, rng),
        })

    for a in assets:
        if a["health_band"] not in ("critical", "poor"):
            continue
        when = today - timedelta(days=rng.randint(0, 45))
        msg = f"{a['asset_name']} ({a['asset_code']}) is now at {a['health_band']} health."
        holder = current_assignment.get(a["id"])
        if holder:
            add(holder, "high_risk_asset", "Assigned vehicle needs attention", msg, when, asset_id=a["id"])
        for admin in admins_by_wh.get(a["_warehouse_short"], [])[:3]:
            add(admin["id"], "high_risk_asset", "Asset health alert", msg, when, asset_id=a["id"])

    for t in tickets:
        when = t["opened_at"].date()
        if (today - when).days > 90:
            continue
        add(t["assigned_to"], "ticket_created", "Ticket assigned to you",
            f"{t['ticket_number']}: {t['title']}", when, ticket_id=t["id"])
        if t["status"] in ("resolved", "closed") and t["resolved_at"]:
            add(t["created_by"], "ticket_resolved", "Your ticket was resolved",
                f"{t['ticket_number']}: {t['title']}", t["resolved_at"].date(), ticket_id=t["id"])

    return rows
