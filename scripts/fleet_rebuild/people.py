"""Staff roster: super admins, warehouse admins, demo pairs and department users.

Produces account *specs*, not final rows — ``id`` is left unset because a
profile's primary key must equal the ``auth.users`` id that Supabase mints when
the account is created. The loader fills it in after each auth user exists.
"""

from __future__ import annotations

import random

from . import config as C
from .names import EmailAllocator, make_employee_id, make_person, make_phone

# Job titles by department, used for profile.meta so the roster reads like a
# real establishment rather than an undifferentiated list of "users".
TITLES = {
    "LOG": ["Driver", "Driver", "Driver", "Forklift Operator", "Forklift Operator",
            "Senior Driver", "Shift Lead - Fleet", "Dispatch Coordinator"],
    "MECH": ["Vehicle Technician", "Vehicle Technician", "Senior Technician",
             "Hydraulics Technician", "Brake & Tyre Technician", "Workshop Foreman"],
    "ELEC": ["Auto Electrician", "Auto Electrician", "Senior Auto Electrician",
             "Battery Systems Technician", "Charging Infrastructure Technician"],
    "SFT": ["Telematics Engineer", "Systems Support Engineer",
            "Data Integration Engineer", "Platform Support Analyst"],
    "ADM": ["Administrative Officer", "Compliance Officer",
            "Scheduling Coordinator", "Records Officer"],
}

ADMIN_TITLES = [
    "Warehouse Manager", "Assistant Warehouse Manager", "Fleet Manager",
    "Maintenance Manager", "Operations Manager", "Safety & Compliance Manager",
    "Logistics Manager", "Shift Manager", "Inventory Manager", "Depot Manager",
]


def build_roster(rng: random.Random) -> list[dict]:
    """Every account to create, in load order (super admins first)."""
    emails = EmailAllocator(C.EMAIL_DOMAIN)
    roster: list[dict] = []

    # ── Super admins ─────────────────────────────────────────────────────────
    # Global: they can sign into any warehouse, so warehouse_id/department_id
    # stay NULL rather than pinning them to one site.
    for sa in C.SUPER_ADMINS:
        roster.append({
            "email": emails.reserve(sa["email"]),
            "password": C.PASSWORD_SUPER_ADMIN,
            "full_name": sa["full_name"],
            "role": "super_admin",
            "status": "active",
            "warehouse_short": None,
            "dept_key": None,
            "employee_id": None,
            "phone": make_phone(rng),
            "meta": {"title": "Super Administrator", "scope": "global"},
        })

    # ── Per warehouse ────────────────────────────────────────────────────────
    for w in C.WAREHOUSES:
        short = w["short"]
        city_slug = w["city"].lower()
        head = C.HEADCOUNT[short]
        seq = 1

        # Demo pair — fixed, memorable credentials for demonstrations.
        roster.append({
            "email": emails.reserve(C.DEMO_ADMIN_TEMPLATE.format(city=city_slug)),
            "password": C.PASSWORD_DEMO_ADMIN,
            "full_name": f"Demo Admin ({w['city']})",
            "role": "admin", "status": "active",
            "warehouse_short": short, "dept_key": "ADM",
            "employee_id": make_employee_id(short, seq), "phone": make_phone(rng),
            "meta": {"title": "Demo Administrator", "demo_account": True},
        })
        seq += 1
        roster.append({
            "email": emails.reserve(C.DEMO_USER_TEMPLATE.format(city=city_slug)),
            "password": C.PASSWORD_DEMO_USER,
            "full_name": f"Demo User ({w['city']})",
            "role": "user", "status": "active",
            "warehouse_short": short, "dept_key": "ADM",
            "employee_id": make_employee_id(short, seq), "phone": make_phone(rng),
            "meta": {"title": "Demo User", "demo_account": True},
        })
        seq += 1

        # Warehouse admins.
        for i in range(head["admin"]):
            first, surname = make_person(rng)
            roster.append({
                "email": emails.allocate(first, surname, "adm"),
                "password": C.PASSWORD_ADMIN,
                "full_name": f"{first} {surname}",
                "role": "admin", "status": "active",
                "warehouse_short": short, "dept_key": "ADM",
                "employee_id": make_employee_id(short, seq), "phone": make_phone(rng),
                "meta": {"title": ADMIN_TITLES[i % len(ADMIN_TITLES)]},
            })
            seq += 1

        # Department users.
        for dept in ("LOG", "MECH", "ELEC", "SFT", "ADM"):
            acronym = next(d["acronym"] for d in C.DEPARTMENTS if d["code"] == dept)
            for _ in range(head[dept]):
                first, surname = make_person(rng)
                # A small share of any real roster is not currently active —
                # resigned, on long leave, or suspended pending review.
                roll = rng.random()
                status = "inactive" if roll < 0.03 else ("suspended" if roll < 0.038 else "active")
                roster.append({
                    "email": emails.allocate(first, surname, acronym),
                    "password": C.PASSWORD_USER,
                    "full_name": f"{first} {surname}",
                    "role": "user", "status": status,
                    "warehouse_short": short, "dept_key": dept,
                    "employee_id": make_employee_id(short, seq), "phone": make_phone(rng),
                    "meta": {"title": rng.choice(TITLES[dept])},
                })
                seq += 1

    return roster
