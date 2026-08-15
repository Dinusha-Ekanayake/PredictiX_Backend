"""Apply a SQL migration from docs/migrations against the configured database.

Migrations in this project were previously applied by hand through the Supabase
SQL editor, which leaves no record of what ran where. This runner uses the same
DATABASE_URL the application does, so a migration is applied to exactly the
database the app talks to, and prints the row counts it changed.

Usage:
    python scripts/apply_migration.py 010                 # dry run: show the SQL
    python scripts/apply_migration.py 010 --apply         # execute it

Migrations are expected to be written idempotently (guarded by a WHERE clause or
IF NOT EXISTS), so re-running one is a no-op rather than an error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "docs" / "migrations"


def find_migration(prefix: str) -> Path:
    matches = sorted(MIGRATIONS_DIR.glob(f"{prefix}*.sql"))
    if not matches:
        raise SystemExit(f"No migration matching {prefix!r} in {MIGRATIONS_DIR}")
    if len(matches) > 1:
        raise SystemExit(
            f"{prefix!r} is ambiguous: {', '.join(m.name for m in matches)}"
        )
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", help="migration number, e.g. 010")
    ap.add_argument("--apply", action="store_true",
                    help="execute the migration (otherwise just prints it)")
    args = ap.parse_args()

    path = find_migration(args.prefix)
    sql = path.read_text(encoding="utf-8")

    print(f"=== {path.name} ===")
    if not args.apply:
        print(sql)
        print("--- dry run; pass --apply to execute ---")
        return

    # The file carries its own BEGIN/COMMIT, so drive it outside SQLAlchemy's
    # implicit transaction rather than nesting two.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        result = conn.execute(text(sql))
        rowcount = result.rowcount if result.rowcount is not None else -1

    print(f"applied. rows affected: {rowcount if rowcount >= 0 else 'n/a'}")


if __name__ == "__main__":
    main()
