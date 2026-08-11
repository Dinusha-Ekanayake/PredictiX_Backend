"""Fleet rebuild runner.

Phases are separately invocable so each destructive step can be verified before
the next one runs:

    python scripts/rebuild_fleet.py generate    # offline, writes a cache + CSVs
    python scripts/rebuild_fleet.py superadmins # create + verify login (SAFE)
    python scripts/rebuild_fleet.py wipe        # DESTRUCTIVE - truncate + drop old accounts
    python scripts/rebuild_fleet.py accounts    # create the remaining ~1330 users
    python scripts/rebuild_fleet.py load        # load warehouses..notifications
    python scripts/rebuild_fleet.py verify      # row counts + integrity checks

`superadmins` runs before `wipe` on purpose: the replacement administrator
accounts are proven to work while the old ones still exist, so a failure at
that point costs nothing.
"""

from __future__ import annotations

import pickle
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleet_rebuild import auth_users, config as C, load as L  # noqa: E402
from fleet_rebuild.db import connect, count  # noqa: E402
from fleet_rebuild.generate import generate, write_csvs  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / "scripts" / ".fleet_cache.pkl"
MIGRATION = "docs/migrations/009_add_parking_slot_and_health_pct_checks.sql"


def _load_cache() -> dict:
    if not CACHE.exists():
        sys.exit("No generation cache. Run: python scripts/rebuild_fleet.py generate")
    return pickle.load(CACHE.open("rb"))


def cmd_generate(today: date) -> None:
    tables = generate(today=today)
    pickle.dump(tables, CACHE.open("wb"))
    for k, v in tables.items():
        print(f"  {k:<26} {len(v):>7,}")
    print(f"\n  cache -> {CACHE}")


def cmd_superadmins() -> None:
    tables = _load_cache()
    sb = auth_users.client()
    existing = {u.email: str(u.id) for u in auth_users.list_all_users(sb) if u.email}
    supers = [p for p in tables["profiles"] if p["role"] == "super_admin"]
    print(f"  creating/updating {len(supers)} super admins "
          f"({sum(1 for s in supers if s['email'] in existing)} already exist)")
    ids, failures = auth_users.create_users(sb, supers, existing_by_email=existing)
    for email, err in failures:
        print(f"  FAILED {email}: {err}")
    if failures:
        sys.exit("aborting: super-admin creation failed, nothing destroyed")

    email = supers[0]["email"]
    ok, msg = auth_users.verify_login(email, C.PASSWORD_SUPER_ADMIN)
    print(f"  login check {email}: {'OK' if ok else 'FAILED'} ({msg})")
    if not ok:
        sys.exit("aborting: super admin cannot sign in, nothing destroyed")
    pickle.dump(ids, (CACHE.parent / ".superadmin_ids.pkl").open("wb"))
    print("  super admins verified - safe to proceed to wipe")


def cmd_wipe() -> None:
    keep = pickle.load((CACHE.parent / ".superadmin_ids.pkl").open("rb"))
    conn = connect()
    print("  truncating fleet tables...")
    L.wipe(conn)
    print("  applying migration 009 (empty tables validate instantly)...")
    L.apply_migration(conn, MIGRATION)
    print(f"  deleting old auth users (keeping {len(keep)} verified super admins)...")
    sb = auth_users.client()
    deleted, failures = auth_users.delete_users_except(sb, set(keep.values()))
    for email, err in failures[:10]:
        print(f"  FAILED delete {email}: {err}")
    print(f"  deleted {deleted} accounts, {len(failures)} failures")
    for t in L.PRESERVE_TABLES:
        print(f"  preserved {t:<18} {count(conn, t):>5} rows")
    conn.close()


def cmd_accounts() -> None:
    tables = _load_cache()
    keep = pickle.load((CACHE.parent / ".superadmin_ids.pkl").open("rb"))
    sb = auth_users.client()
    existing = {u.email: str(u.id) for u in auth_users.list_all_users(sb) if u.email}
    rest = [p for p in tables["profiles"] if p["role"] != "super_admin"]
    print(f"  creating {len(rest)} accounts (this takes a while)...")
    ids, failures = auth_users.create_users(sb, rest, existing_by_email=existing)
    ids.update(keep)
    for email, err in failures[:20]:
        print(f"  FAILED {email}: {err}")
    print(f"  created {len(ids)} total, {len(failures)} failures")
    pickle.dump(ids, (CACHE.parent / ".account_ids.pkl").open("wb"))


def cmd_load() -> None:
    tables = _load_cache()
    ids = pickle.load((CACHE.parent / ".account_ids.pkl").open("rb"))
    placeholder_to_real = {
        p["id"]: ids[p["email"]] for p in tables["profiles"] if p["email"] in ids
    }
    print(f"  remapping {len(placeholder_to_real)}/{len(tables['profiles'])} person ids")
    L.remap_person_ids(tables, placeholder_to_real)
    valid = set(placeholder_to_real.values())
    dropped = L.drop_rows_with_unmapped_people(tables, valid)
    for t, n in dropped.items():
        print(f"  dropped {n} {t} rows referencing an uncreated account")

    conn = connect()
    # Warehouses and departments first — profiles carry FKs to both.
    L.load_tables(conn, {k: tables[k] for k in ("warehouses", "departments")})
    L.upsert_profiles(conn, [p for p in tables["profiles"] if p["id"] in valid])
    # Then everything that references a profile.
    L.load_tables(conn, {k: v for k, v in tables.items()
                         if k in L.LOAD_ORDER and k not in ("warehouses", "departments")})
    conn.close()
    write_csvs(tables)
    print(f"  CSV evidence -> {C.OUT_DIR}")


def cmd_passwords() -> None:
    tables = _load_cache()
    ids = pickle.load((CACHE.parent / ".account_ids.pkl").open("rb"))
    people = [p for p in tables["profiles"] if p["email"] in ids]
    for p in people:
        p["id"] = ids[p["email"]]
    conn = connect()
    print(f"  hashing {len(people)} passwords (bcrypt, one salt each)...")
    L.set_password_hashes(conn, people)
    conn.close()


def cmd_export() -> None:
    """Dump every public table straight from the database to CSV.

    Exported from the DB rather than from the generator's in-memory tables so
    the evidence reflects what is actually stored — including rows the
    application itself produced (PdM predictions, prediction history, the
    notifications the pipeline raised) and any post-load corrections.

    `profiles` is exported without meta.password_hash: this folder is a record
    of the data, not a credential store.
    """
    import csv as _csv

    conn = connect()
    out = Path(C.OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname='public' AND c.relkind='r' ORDER BY 1
        """)
        tables = [r[0] for r in cur.fetchall()]

    total = 0
    for t in tables:
        with conn.cursor() as cur:
            if t == "profiles":
                cur.copy_expert(
                    "COPY (SELECT id, employee_id, full_name, email, phone, role, "
                    "status, warehouse_id, department_id, avatar_url, "
                    "(meta - 'password_hash') AS meta, created_at, updated_at "
                    "FROM public.profiles) TO STDOUT WITH (FORMAT csv, HEADER true)",
                    (out / f"{t}.csv").open("w", newline="", encoding="utf-8"),
                )
            else:
                cur.copy_expert(
                    f'COPY public."{t}" TO STDOUT WITH (FORMAT csv, HEADER true)',
                    (out / f"{t}.csv").open("w", newline="", encoding="utf-8"),
                )
        with (out / f"{t}.csv").open(newline="", encoding="utf-8") as fh:
            r = _csv.reader(fh)
            next(r, None)
            n = sum(1 for _ in r)
        total += n
        print(f"  {t:<32} {n:>8,}")
    print(f"  {'TOTAL':<32} {total:>8,}  -> {out}")
    conn.close()


def cmd_verify() -> None:
    conn = connect()
    for t in L.LOAD_ORDER + ["profiles"] + L.PRESERVE_TABLES:
        print(f"  {t:<24} {count(conn, t):>8,}")
    conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    today = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    {
        "generate": lambda: cmd_generate(today),
        "superadmins": cmd_superadmins,
        "wipe": cmd_wipe,
        "accounts": cmd_accounts,
        "load": cmd_load,
        "passwords": cmd_passwords,
        "export": cmd_export,
        "verify": cmd_verify,
    }[cmd]()


if __name__ == "__main__":
    main()
