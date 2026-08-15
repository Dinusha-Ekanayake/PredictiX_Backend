"""Database connection and bulk-insert helpers for the fleet rebuild."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2.extras import execute_values

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = REPO_ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in env})
    return env


def connect(env: dict[str, str] | None = None):
    env = env or load_env()
    u = urlparse(env["DATABASE_URL"])
    conn = psycopg2.connect(
        host=u.hostname, port=u.port, user=u.username,
        password=unquote(u.password or ""), dbname=u.path.lstrip("/"),
        connect_timeout=30,
    )
    conn.autocommit = False
    return conn


# Columns that are jsonb in the database — Python dict/list must be serialised.
JSON_COLUMNS = {"metadata", "meta", "reading_payload", "contributing_factors",
                "top_explanations", "feature_snapshot"}


def _adapt(col: str, value):
    if col in JSON_COLUMNS:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (datetime, date)):
        return value
    return value


def bulk_insert(conn, table: str, rows: list[dict], columns: list[str] | None = None,
                page_size: int = 1000) -> int:
    """Multi-row INSERT. Keys starting with ``_`` are generator-internal and skipped."""
    if not rows:
        return 0
    cols = columns or [c for c in rows[0] if not c.startswith("_")]
    quoted = ", ".join(f'"{c}"' for c in cols)
    values = [tuple(_adapt(c, r.get(c)) for c in cols) for r in rows]
    with conn.cursor() as cur:
        execute_values(
            cur, f'INSERT INTO public."{table}" ({quoted}) VALUES %s',
            values, page_size=page_size,
        )
    return len(values)


def count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM public."{table}"')
        return cur.fetchone()[0]
