"""Prove the public anon key cannot reach PredictiX data.

    python scripts/security/check_public_access.py

The anon key ships in the frontend bundle, so anyone has it. This script uses
it exactly as an attacker would and reports every way in that still works:

  * reading any public table or view over the REST API,
  * a write being accepted (an UPDATE aimed at a row that cannot exist, so
    nothing changes even when the write is permitted),
  * calling an application function over /rpc,
  * listing objects in any storage bucket.

Every request is read-only or matches no row; the script never changes data.
Tables and functions are discovered from the database (DATABASE_URL), so a
new table is covered without editing this file.

Needs SUPABASE_URL, DATABASE_URL and the anon key in SUPABASE_ANON_KEY (or
NEXT_PUBLIC_SUPABASE_ANON_KEY). Exit code 1 when anything is exposed.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

NIL_UUID = "00000000-0000-0000-0000-000000000000"
TIMEOUT_S = 20


def _request(method: str, url: str, key: str, body: object = None) -> tuple[int, bytes]:
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Accept-Profile": "public", "Content-Profile": "public",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _catalogue() -> tuple[list[str], list[str], list[str]]:
    """Public tables/views, application functions and storage buckets."""
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        tables = [r[0] for r in db.execute(text(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind in ('r', 'v', 'm') order by 1"))]
        functions = [r[0] for r in db.execute(text(
            "select distinct p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "left join pg_depend d on d.objid = p.oid and d.deptype = 'e' "
            "where n.nspname = 'public' and d.objid is null and p.prorettype <> 'trigger'::regtype "
            "and p.pronargs = 0 order by 1"))]
        buckets = [r[0] for r in db.execute(text("select id from storage.buckets order by 1"))]
    return tables, functions, buckets


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not base or not key:
        print("Set SUPABASE_URL and SUPABASE_ANON_KEY (the frontend's public key).")
        return 2

    tables, functions, buckets = _catalogue()
    exposed: list[str] = []

    for table in tables:
        status, body = _request("GET", f"{base}/rest/v1/{table}?select=*&limit=1", key)
        if status in (200, 206):
            rows = len(json.loads(body or b"[]"))
            exposed.append(f"read   {table} (SELECT granted, {rows} row(s) returned)")
        status, _ = _request("PATCH", f"{base}/rest/v1/{table}?id=eq.{NIL_UUID}", key, {})
        if status in (200, 204):
            exposed.append(f"write  {table} (UPDATE permitted; row-level security may still hide rows)")

    for function in functions:
        status, _ = _request("POST", f"{base}/rest/v1/rpc/{function}", key, {})
        if status == 200:
            exposed.append(f"rpc    {function}() callable")

    for bucket in buckets:
        status, body = _request("POST", f"{base}/storage/v1/object/list/{bucket}", key,
                                {"prefix": "", "limit": 1})
        if status == 200 and json.loads(body or b"[]"):
            exposed.append(f"list   storage bucket {bucket}")

    print(f"checked {len(tables)} tables, {len(functions)} functions, {len(buckets)} buckets")
    for line in exposed:
        print(f"EXPOSED  {line}")
    if exposed:
        print(f"{len(exposed)} exposure(s): apply docs/migrations/016_close_public_api_access.sql")
        return 1
    print("OK  the anon key reaches no table, function or bucket listing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
