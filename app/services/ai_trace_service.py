"""Reading AI audit traces (the ai_traces table written by app/ai/agent/tracing.py).

Visibility follows the rest of the API: a user sees their own traces, an
admin those of their active warehouse, a super admin all of them.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import is_admin_role, is_super_admin, scoped_warehouse_id

_COLUMNS = ("id, created_at, channel, user_id, role, warehouse_id, question, intent, "
            "answer, status, duration_ms, steps")
_NO_MATCH = "00000000-0000-0000-0000-000000000000"
CHANNELS = ("chatbot", "report")


def _parse_uuid(value: Optional[str]) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None


def _visible(row: Any, viewer: Any) -> bool:
    if is_super_admin(viewer):
        return True
    if str(row["user_id"]) == str(getattr(viewer, "id", "")):
        return True
    if is_admin_role(viewer):
        wh_id = scoped_warehouse_id(viewer)
        return bool(wh_id) and str(row["warehouse_id"]) == wh_id
    return False


def _to_dict(row: Any, *, with_steps: bool) -> dict:
    out = {
        "trace_id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "channel": row["channel"],
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "role": row["role"],
        "warehouse_id": str(row["warehouse_id"]) if row["warehouse_id"] else None,
        "question": row["question"],
        "intent": row["intent"],
        "answer": row["answer"],
        "status": row["status"],
        "duration_ms": row["duration_ms"],
    }
    if with_steps:
        out["steps"] = row["steps"]
    return out


def get_trace(db: Session, trace_id: str, viewer: Any) -> Optional[dict]:
    """The full trace, or None when it does not exist or the viewer may not see it."""
    trace_uuid = _parse_uuid(trace_id)
    if trace_uuid is None:
        return None
    row = db.execute(text(f"SELECT {_COLUMNS} FROM ai_traces WHERE id = CAST(:id AS uuid)"),
                     {"id": trace_uuid}).mappings().first()
    if row is None or not _visible(row, viewer):
        return None
    return _to_dict(row, with_steps=True)


def list_traces(
    db: Session,
    viewer: Any,
    *,
    user_id: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Recent traces the viewer may see, newest first, without their steps.

    Raises ValueError for a malformed user_id or an unknown channel.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
    if is_super_admin(viewer):
        pass
    elif is_admin_role(viewer):
        clauses.append("warehouse_id = CAST(:wh AS uuid)")
        params["wh"] = scoped_warehouse_id(viewer) or _NO_MATCH
    else:
        clauses.append("user_id = CAST(:me AS uuid)")
        params["me"] = str(getattr(viewer, "id", _NO_MATCH))
    if user_id:
        parsed = _parse_uuid(user_id)
        if parsed is None:
            raise ValueError("user_id must be a UUID")
        clauses.append("user_id = CAST(:uid AS uuid)")
        params["uid"] = parsed
    if channel:
        if channel not in CHANNELS:
            raise ValueError("channel must be chatbot or report")
        clauses.append("channel = :channel")
        params["channel"] = channel
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(
        f"SELECT {_COLUMNS} FROM ai_traces {where} ORDER BY created_at DESC LIMIT :limit"
    ), params).mappings().all()
    return [_to_dict(r, with_steps=False) for r in rows]
