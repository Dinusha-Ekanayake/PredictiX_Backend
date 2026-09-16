"""Wipes the old fleet and loads the generated one.

Phase order is chosen so the operator is never locked out: the new super-admin
accounts are created and a real sign-in is verified *before* anything is
deleted. If account creation fails, nothing has been destroyed yet.
"""

from __future__ import annotations

from pathlib import Path

from .db import bulk_insert, connect, count

# Cleared by the rebuild. Order does not matter, CASCADE resolves dependants, 
# but `profiles` is deliberately absent: profiles are removed by deleting their
# auth.users parent (FK ON DELETE CASCADE), and recreated by the
# on_auth_user_created trigger when the new accounts are made.
WIPE_TABLES = [
    "prediction_feature_importance", "prediction_explanations",
    "asset_cost_predictions", "asset_failure_predictions", "ticket_predictions",
    "prediction_runs", "pdm_prediction_history", "pdm_batch_predictions",
    "sensor_readings", "maintenance_events", "asset_logs", "asset_status_history",
    "asset_documents", "service_reminder_log", "asset_assignments",
    "report_sources", "reports", "ticket_comments", "ticket_status_history",
    "ticket_attachments", "tickets", "notifications", "api_usage_logs",
    "assets", "departments", "warehouses",
]

# Deliberately preserved.
#   model_registry  - prediction_runs.model_id is ON DELETE RESTRICT, and these
#                     8 rows describe the deployed models, not fleet data.
#   faqs            - static helpdesk content the chatbot's handle_faq tool
#                     serves; nothing to do with the fleet.
#   knowledge_base  - RAG store (currently empty); not fleet data.
PRESERVE_TABLES = ["model_registry", "faqs", "knowledge_base"]

# Every column that holds a profile id, so placeholder ids generated offline can
# be swapped for the real auth.users ids once the accounts exist.
PERSON_REFS = {
    "assets": ["assigned_to", "created_by"],
    "asset_assignments": ["user_id", "assigned_by"],
    "maintenance_events": ["performed_by"],
    "tickets": ["created_by", "assigned_to", "reviewed_by"],
    "ticket_comments": ["user_id"],
    "ticket_status_history": ["changed_by"],
    "notifications": ["user_id"],
}

# Load order respects foreign keys.
LOAD_ORDER = [
    "warehouses", "departments", "assets", "sensor_readings",
    "maintenance_events", "asset_assignments", "tickets", "ticket_comments",
    "ticket_status_history", "notifications",
]


def remap_person_ids(tables: dict[str, list[dict]], placeholder_to_real: dict[str, str]) -> int:
    """Rewrite every profile reference from placeholder uuid to real auth id."""
    changed = 0
    for person in tables["profiles"]:
        real = placeholder_to_real.get(person["id"])
        if real:
            person["_placeholder_id"] = person["id"]
            person["id"] = real
            changed += 1
    for table, cols in PERSON_REFS.items():
        for row in tables.get(table, []):
            for col in cols:
                val = row.get(col)
                if val and val in placeholder_to_real:
                    row[col] = placeholder_to_real[val]
                    changed += 1
    return changed


def drop_rows_with_unmapped_people(tables: dict[str, list[dict]], valid: set[str]) -> dict[str, int]:
    """Remove rows still pointing at a person who was never created.

    A NOT NULL person reference (e.g. ticket_comments.user_id) makes the row
    unloadable, so it is dropped and reported. Nullable references are blanked
    instead of dropping otherwise-good data.
    """
    required = {"asset_assignments": ["user_id"], "ticket_comments": ["user_id"],
                "notifications": ["user_id"]}
    dropped: dict[str, int] = {}
    for table, cols in PERSON_REFS.items():
        rows = tables.get(table, [])
        must = set(required.get(table, []))
        keep = []
        for row in rows:
            ok = True
            for col in cols:
                val = row.get(col)
                if val and val not in valid:
                    if col in must:
                        ok = False
                        break
                    row[col] = None
            if ok:
                keep.append(row)
        if len(keep) != len(rows):
            dropped[table] = len(rows) - len(keep)
            tables[table] = keep
    return dropped


def wipe(conn, progress=print) -> dict[str, int]:
    """TRUNCATE the fleet tables. Destructive; run only after the backup and
    after the replacement accounts are confirmed working.

    Note that CASCADE reaches further than this list: it truncates every table
    holding a foreign key *to* one of these. ``profiles`` references
    ``warehouses`` and ``departments``, so profiles are emptied here too even
    though the table is not named, which is why profiles are written with an
    UPSERT (see ``upsert_profiles``) rather than an UPDATE of trigger-created
    rows.
    """
    before = {t: count(conn, t) for t in WIPE_TABLES}
    joined = ", ".join(f'public."{t}"' for t in WIPE_TABLES)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")
    conn.commit()
    progress(f"  truncated {len(WIPE_TABLES)} tables ({sum(before.values()):,} rows)")
    return before


def apply_migration(conn, path: str, progress=print) -> None:
    sql = Path(path).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    progress(f"  applied {Path(path).name}")


def upsert_profiles(conn, profiles: list[dict], progress=print) -> int:
    """Write the full profile row for every account.

    An UPSERT rather than an UPDATE because the trigger-created row cannot be
    relied on to still exist: ``profiles`` carries foreign keys to
    ``warehouses`` and ``departments``, so ``TRUNCATE warehouses CASCADE``
    during the wipe also truncates ``profiles``, CASCADE propagates to
    *referencing* tables, not just referenced ones. Any account created before
    the wipe therefore loses its profile, and an UPDATE-only path would silently
    leave that person unable to resolve a profile at sign-in.
    """
    import json

    rows = [
        (p["id"], p["employee_id"], p["full_name"], p["email"], p["phone"],
         p["role"], p["status"], p["warehouse_id"], p["department_id"],
         json.dumps(p["meta"], ensure_ascii=False))
        for p in profiles
    ]
    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO public.profiles
                (id, employee_id, full_name, email, phone, role, status,
                 warehouse_id, department_id, meta)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                employee_id   = EXCLUDED.employee_id,
                full_name     = EXCLUDED.full_name,
                email         = EXCLUDED.email,
                phone         = EXCLUDED.phone,
                role          = EXCLUDED.role,
                status        = EXCLUDED.status,
                warehouse_id  = EXCLUDED.warehouse_id,
                department_id = EXCLUDED.department_id,
                meta          = EXCLUDED.meta,
                updated_at    = now()
        """, rows, page_size=500, template="(%s::uuid,%s,%s,%s,%s,%s::app_role,"
                                           "%s::user_status,%s::uuid,%s::uuid,%s::jsonb)")
        written = cur.rowcount
    conn.commit()
    progress(f"  profiles upserted: {written}/{len(profiles)}")
    return written


def set_password_hashes(conn, profiles: list[dict], progress=print) -> int:
    """Write a bcrypt hash into ``profiles.meta.password_hash`` for each account.

    This is what actually governs signing in. The backend's ``POST /auth/login``
    (app/routers/auth.py::_authenticate_profile) checks
    ``profile.meta['password_hash']`` first and only falls back to the single
    global ``DEFAULT_PASSWORD`` when no hash is stored, so without this step
    every account would share one password regardless of what was set in
    Supabase Auth. The Supabase accounts are still required (``profiles.id``
    is a foreign key to ``auth.users``) and are what Google/Supabase-side flows
    use, but they are not consulted by this login path.

    Each account gets its own salt rather than reusing one hash per distinct
    password, so identical stored hashes never reveal which accounts share a
    password.
    """
    from psycopg2.extras import execute_values

    from app.core.security import hash_password

    rows = [(p["id"], hash_password(p["password"])) for p in profiles]
    with conn.cursor() as cur:
        execute_values(cur, """
            UPDATE public.profiles AS pr
               SET meta = coalesce(pr.meta, '{}'::jsonb)
                          || jsonb_build_object('password_hash', v.pw),
                   updated_at = now()
              FROM (VALUES %s) AS v (id, pw)
             WHERE pr.id = v.id::uuid
        """, rows, page_size=200)
    conn.commit()
    progress(f"  password hashes written: {len(rows)}")
    return len(rows)


def load_tables(conn, tables: dict[str, list[dict]], progress=print) -> dict[str, int]:
    loaded: dict[str, int] = {}
    for name in LOAD_ORDER:
        rows = tables.get(name, [])
        if not rows:
            continue
        n = bulk_insert(conn, name, rows)
        conn.commit()
        loaded[name] = n
        progress(f"  loaded {name:<24} {n:>7,}")
    return loaded
