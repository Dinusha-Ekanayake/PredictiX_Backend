"""Sources derived from PredictiX's own data.

D01, ticket issue patterns: for every warehouse, each recurring issue (same
title and description once the vehicle line is removed) becomes one passage
with how often it occurs there, how it is usually categorised and
prioritised, how long it takes to resolve and which vehicles it affects.
These are exact aggregates of the tickets table, so the passages hold the
warehouse's own experience without exposing any single ticket or person.

Individual tickets and maintenance events are deliberately not embedded:
they are structured records, answered precisely by the chatbot's SQL agent,
and their text is templated, so embedding it would add volume, not knowledge.

The snapshot (aggregates only, already redacted) is what gets archived as the
source's "original", so no raw ticket rows are copied out of the database.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.kb.pipeline.extract import Block
from app.kb.pipeline.privacy import Redactor

_VEHICLE_LINE = re.compile(r"\s*\n\s*\n?\s*Vehicle:.*$", re.S)
_DONE = {"resolved", "closed"}
_ACTIVE = {"open", "in_progress"}

_TICKETS = text("""
    SELECT t.warehouse_id::text AS warehouse_id, w.name AS warehouse, t.title, t.description,
           t.status::text AS status, t.final_category::text AS category, t.final_priority::text AS priority,
           t.opened_at, COALESCE(t.resolved_at, t.closed_at) AS done_at,
           a.make, a.model, a.category AS asset_category
    FROM tickets t
    JOIN warehouses w ON w.id = t.warehouse_id
    LEFT JOIN assets a ON a.id = t.asset_id
""")


def _shares(values: list[str], top: int = 2) -> list[list[Any]]:
    counts = Counter(v for v in values if v)
    total = sum(counts.values())
    return [[k, round(100 * n / total)] for k, n in counts.most_common(top)] if total else []


def snapshot_ticket_patterns(db: Session) -> bytes:
    """Deterministic JSON of per-warehouse issue patterns, with personal data removed."""
    redact = Redactor(r[0] for r in db.execute(text("SELECT full_name FROM profiles WHERE full_name IS NOT NULL")))
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    latest = None
    for row in db.execute(_TICKETS).mappings():
        issue = redact(_VEHICLE_LINE.sub("", row["description"] or "").strip())
        title = redact((row["title"] or "").strip())
        groups[(row["warehouse_id"], row["warehouse"], title, issue)].append(dict(row))
        latest = max(latest, row["opened_at"]) if latest else row["opened_at"]

    patterns = []
    for (wh_id, wh_name, title, issue), rows in sorted(groups.items()):
        opened = sorted(r["opened_at"] for r in rows)
        days = [
            (r["done_at"] - r["opened_at"]).total_seconds() / 86400
            for r in rows if r["status"] in _DONE and r["done_at"] and r["done_at"] >= r["opened_at"]
        ]
        vehicles = Counter(f"{r['make']} {r['model']}".strip() for r in rows if r["make"])
        patterns.append({
            "warehouse_id": wh_id,
            "warehouse": wh_name,
            "title": title,
            "issue": issue,
            "tickets": len(rows),
            "active": sum(r["status"] in _ACTIVE for r in rows),
            "done": sum(r["status"] in _DONE for r in rows),
            "first_month": opened[0].strftime("%Y-%m"),
            "last_month": opened[-1].strftime("%Y-%m"),
            "categories": _shares([r["category"] for r in rows]),
            "priorities": _shares([r["priority"] for r in rows], top=3),
            "median_days_to_resolve": round(statistics.median(days), 1) if days else None,
            "vehicles": vehicles.most_common(3),
            "asset_categories": sorted({r["asset_category"] for r in rows if r["asset_category"]}),
        })
    snapshot = {
        "format": "db_ticket_patterns",
        "data_up_to": latest.astimezone(timezone.utc).strftime("%Y-%m-%d") if latest else None,
        "patterns": patterns,
    }
    return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def _percent_list(pairs: list[list[Any]]) -> str:
    return ", ".join(f"{name} ({pct}%)" for name, pct in pairs) or "not recorded"


def blocks_from_ticket_patterns(content: bytes) -> list[Block]:
    """One block per warehouse and issue pattern, tagged with its warehouse."""
    snapshot = json.loads(content)
    cutoff = snapshot.get("data_up_to") or "the latest snapshot"
    blocks = []
    for p in snapshot["patterns"]:
        lines = [
            f"Issue pattern at {p['warehouse']}: {p['title']}.",
            f"Typical report: {p['issue']}" if p["issue"] else "",
            f"Occurrences at {p['warehouse']}: {p['tickets']} tickets between {p['first_month']} and "
            f"{p['last_month']}; {p['done']} resolved or closed, {p['active']} still open (data up to {cutoff}).",
            f"Usually categorised as {_percent_list(p['categories'])}. "
            f"Final priority: {_percent_list(p['priorities'])}.",
            f"Median time to resolve: {p['median_days_to_resolve']} days."
            if p["median_days_to_resolve"] is not None else "No resolved tickets yet for this issue here.",
            "Most affected vehicles: " + ", ".join(f"{v} ({n})" for v, n in p["vehicles"]) + "."
            if p["vehicles"] else "",
        ]
        blocks.append(Block(
            text=" ".join(l for l in lines if l),
            section=f"{p['warehouse']} - {p['title']}",
            page=None,
            warehouse_id=p["warehouse_id"],
        ))
    return blocks


INTERNAL_FORMATS = {"db_ticket_patterns": (snapshot_ticket_patterns, blocks_from_ticket_patterns)}


def snapshot_time() -> datetime:
    return datetime.now(timezone.utc)
