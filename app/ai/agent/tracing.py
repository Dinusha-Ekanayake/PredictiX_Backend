"""Audit trail for AI answers: how each chatbot reply or AI report was produced.

A trace is opened per request (start_trace), collects a step for every
decision the pipeline makes (record), and is saved to the ai_traces table when
the request finishes (finish_trace). Its id goes back to the caller with the
answer, so anyone holding the id can ask an admin how that answer was made.

Steps recorded across the pipeline:
  intent        how the question was routed, and whether the LLM decided it
  rewrite       a follow-up question rewritten using the chat history
  handler       the tool that answered
  retrieval     corpus, method, query used and every hit with source, id,
                title and score
  llm_call      purpose, model, latency, outcome, a preview of the reply
  sql           generated SQL, whether the sandbox accepted it, rows returned
  action        a create/update action and its outcome
  error         anything that went wrong on the way

The trace never changes the answer and never fails a request: recording is a
no-op outside a trace, and a failed save is logged and dropped.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("predictix.trace")

MAX_STEPS = 200
MAX_TEXT = 2000

_current: ContextVar[Optional["AgentTrace"]] = ContextVar("predictix_agent_trace", default=None)


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + " …[truncated]"
    if isinstance(value, dict):
        return {str(k): _clip(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in list(value)[:50]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clip(str(value))


@dataclass
class AgentTrace:
    channel: str
    user_id: Optional[str]
    role: Optional[str]
    warehouse_id: Optional[str]
    question: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps: list[dict] = field(default_factory=list)
    intent: Optional[str] = None
    _t0: float = field(default_factory=time.monotonic)

    def add(self, kind: str, **data: Any) -> None:
        if len(self.steps) >= MAX_STEPS:
            return
        self.steps.append({"t_ms": int((time.monotonic() - self._t0) * 1000), "kind": kind, **_clip(data)})

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)


def start_trace(*, channel: str, user: Any, question: str, warehouse_id: Optional[str] = None) -> AgentTrace:
    """Open a trace for this request and make it current."""
    from app.deps import scoped_warehouse_id

    uid = getattr(user, "id", None)
    trace = AgentTrace(
        channel=channel,
        user_id=str(uid) if uid else None,
        role=str(getattr(user, "role", "") or "") or None,
        warehouse_id=warehouse_id or scoped_warehouse_id(user),
        question=_clip(question or ""),
    )
    _current.set(trace)
    return trace


def current_trace() -> Optional[AgentTrace]:
    return _current.get()


def record(kind: str, **data: Any) -> None:
    """Add a step to the current trace; does nothing when no trace is open."""
    trace = _current.get()
    if trace is not None:
        try:
            trace.add(kind, **data)
        except Exception:  # recording must never affect the answer
            log.debug("trace record failed", exc_info=True)


def set_intent(intent: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.intent = intent


def finish_trace(*, answer: str, status: str = "ok", **result: Any) -> Optional[str]:
    """Close the current trace, save it, and return its id."""
    trace = _current.get()
    if trace is None:
        return None
    _current.set(None)
    trace.add("result", status=status, answer_preview=(answer or "")[:500], **result)
    _save(trace, answer, status)
    return trace.trace_id


def _save(trace: AgentTrace, answer: str, status: str) -> None:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO ai_traces (id, created_at, channel, user_id, role, warehouse_id, "
                "question, intent, answer, status, duration_ms, steps) VALUES ("
                "CAST(:id AS uuid), :created_at, :channel, CAST(:user_id AS uuid), :role, "
                "CAST(:warehouse_id AS uuid), :question, :intent, :answer, :status, :duration_ms, "
                "CAST(:steps AS jsonb))"
            ), {
                "id": trace.trace_id,
                "created_at": trace.created_at,
                "channel": trace.channel,
                "user_id": _uuid_or_none(trace.user_id),
                "role": trace.role,
                "warehouse_id": _uuid_or_none(trace.warehouse_id),
                "question": trace.question,
                "intent": trace.intent,
                "answer": _clip(answer or ""),
                "status": status,
                "duration_ms": trace.duration_ms,
                "steps": json.dumps(trace.steps, default=str),
            })
            db.commit()
    except Exception as exc:
        # The table may not exist yet (migration 013), or the database may be
        # briefly unavailable. The answer has already been produced either way.
        log.warning("Could not save AI trace %s: %s", trace.trace_id, exc)


def _uuid_or_none(value: Optional[str]) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except ValueError:
        return None
