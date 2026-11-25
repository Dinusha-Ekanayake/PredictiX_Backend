"""Give accounts new, unique random passwords.

The seed passwords used to build the fleet were committed to this public
repository, so every account still on one of them can be signed into by anyone
who reads the history. This replaces them.

For each selected account it generates a random password, stores its bcrypt
hash in profiles.meta.password_hash (what /auth/login checks), and sets the same
password on the Supabase Auth user when one exists. The new passwords are
written to a local CSV (gitignored) so they can be handed to their owners; it
is the only copy, so keep it private and delete it once they are distributed.

Dry run by default, nothing is written:

    python scripts/rotate_passwords.py                      # every account
    python scripts/rotate_passwords.py --roles super_admin admin
    python scripts/rotate_passwords.py --exclude-file keep.txt   # emails to skip
    python scripts/rotate_passwords.py --apply               # really change them

Accounts used by CI (TEST_*_EMAIL) can be excluded, or rotated and the new
values put in the TEST_*_PASSWORD repository secrets.
"""
from __future__ import annotations

import argparse
import csv
import os
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import text  # noqa: E402

load_dotenv()

from app.core.security import hash_password  # noqa: E402
from app.db.session import engine  # noqa: E402

ALPHABET = string.ascii_letters + string.digits + "!@#%^*-_=+"
PASSWORD_LENGTH = 16
OUTPUT_DIR = Path(__file__).resolve().parent / "backups"


def _new_password() -> str:
    while True:
        value = "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))
        if (any(c.islower() for c in value) and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value) and any(not c.isalnum() for c in value)):
            return value


def _supabase_admin():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    from supabase import create_client

    return create_client(url, key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roles", nargs="+", choices=["super_admin", "admin", "user"],
                        default=["super_admin", "admin", "user"])
    parser.add_argument("--exclude-file", type=Path, help="text file with one email per line to leave unchanged")
    parser.add_argument("--apply", action="store_true", help="write the new passwords (default is a dry run)")
    args = parser.parse_args()

    excluded: set[str] = set()
    if args.exclude_file:
        excluded = {line.strip().lower() for line in args.exclude_file.read_text().splitlines() if line.strip()}

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id::text, email, role::text FROM profiles "
                 "WHERE role::text = ANY(:roles) ORDER BY role, email"),
            {"roles": args.roles},
        ).fetchall()
        conn.rollback()
    targets = [r for r in rows if (r.email or "").lower() not in excluded]
    print(f"{len(targets)} account(s) selected ({len(rows) - len(targets)} excluded) for roles {args.roles}.")

    if not args.apply:
        for r in targets[:10]:
            print(f"  would rotate {r.role:12} {r.email}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more")
        print("Dry run: nothing changed. Re-run with --apply to rotate.")
        return

    admin = _supabase_admin()
    if admin is None:
        print("SUPABASE_SERVICE_ROLE_KEY not set: only the app login hash will change, not Supabase Auth.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"rotated_passwords_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    done = auth_failed = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh, engine.begin() as conn:
        writer = csv.writer(fh)
        writer.writerow(["email", "role", "new_password", "supabase_auth_updated"])
        for r in targets:
            password = _new_password()
            conn.execute(
                text("UPDATE profiles SET meta = jsonb_set(COALESCE(meta, '{}'::jsonb), "
                     "'{password_hash}', to_jsonb(CAST(:h AS text))) WHERE id = CAST(:id AS uuid)"),
                {"h": hash_password(password), "id": r.id},
            )
            auth_ok = False
            if admin is not None:
                try:
                    admin.auth.admin.update_user_by_id(r.id, {"password": password})
                    auth_ok = True
                except Exception as exc:  # no Supabase Auth user for this profile, or API error
                    auth_failed += 1
                    print(f"  Supabase Auth not updated for {r.email}: {type(exc).__name__}")
            writer.writerow([r.email, r.role, password, auth_ok])
            done += 1

    print(f"Rotated {done} account(s); Supabase Auth update failed for {auth_failed}.")
    print(f"New passwords: {out_path}  (private, gitignored; delete after handing them out)")


if __name__ == "__main__":
    main()
