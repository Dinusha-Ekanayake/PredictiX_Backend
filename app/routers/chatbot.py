"""PredictiX Chatbot Router, V3 (Token-Optimized, Action-Button enabled)."""
from __future__ import annotations

from typing import Any, Optional, Dict

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext
from app.ai.agent.guardrails import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    bounded_frontend_context,
    clamp,
    sanitize_action_buttons,
)
from app.core.rate_limit import ai_rate_limit
from app.deps import get_current_user, get_db, is_admin_role, is_super_admin, require_user, scoped_warehouse_id
from app.ai.agent.tools import answer_from_help
from app.ai.agent.tracing import finish_trace, record, start_trace
from app.chatbot.knowledge_service import search_help

# Every endpoint here spends Groq quota on the caller's behalf, so a valid
# token is required at the router level, and each user is limited to
# AI_RATE_LIMIT calls per minute (see app/core/rate_limit.py).
router = APIRouter(
    prefix="/chatbot",
    tags=["Chatbot"],
    dependencies=[Depends(require_user), Depends(ai_rate_limit)],
)


# ─── Models ───────────────────────────────────────────────────────────────────

def _bounded_question(value: str) -> str:
    return clamp((value or "").strip(), MAX_QUESTION_CHARS)


class ChatRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def _bound_question(cls, value: str) -> str:
        return _bounded_question(value)


class ChatResponse(BaseModel):
    answer: str
    sources: list[Any] = []
    trace_id: Optional[str] = None


class ChatHistoryTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ActionButton(BaseModel):
    label: str
    path: str


class ToolTraceItem(BaseModel):
    name: str
    args: dict
    result_preview: str


class AgentRequest(BaseModel):
    """Chat input, bounded so one request cannot carry an unbounded prompt.

    Over-long input is trimmed rather than rejected, so a long paste still
    gets an answer.
    """

    question: str
    history: Optional[list[ChatHistoryTurn]] = None
    frontend_context: Optional[dict] = None

    @field_validator("question")
    @classmethod
    def _bound_question(cls, value: str) -> str:
        return _bounded_question(value)

    @field_validator("history")
    @classmethod
    def _bound_history(cls, value):
        if not value:
            return value
        recent = value[-MAX_HISTORY_TURNS:]
        for turn in recent:
            turn.content = clamp(turn.content, MAX_HISTORY_CHARS)
        return recent

    @field_validator("frontend_context")
    @classmethod
    def _bound_context(cls, value):
        return bounded_frontend_context(value)


class AgentResponse(BaseModel):
    answer: str
    action_buttons: list[ActionButton] = []
    tool_trace: list[ToolTraceItem] = []
    iterations: int = 1
    widget_type: Optional[str] = None
    widget_data: Optional[Dict[str, Any]] = None
    # Id of the audit trace for this answer (GET /chatbot/traces/{trace_id}).
    trace_id: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=ChatResponse, deprecated=True)
def ask_question(request: ChatRequest, current_user: object = Depends(get_current_user)):
    """Legacy RAG endpoint, kept for backwards compatibility only.
    The main chatbot should use /chatbot/agent instead.

    Marked deprecated to match reality: the only frontend helper that targets
    this path (askChatbot in lib/apiClient.ts) is not called by any component,
    and it sends no Authorization header, so it would now fail. Every chat
    surface in the product goes through /chatbot/agent.
    """
    # Same guarded, cited help pipeline as the agent's FAQ/knowledge path.
    start_trace(channel="chatbot", user=current_user, question=request.question)
    record("handler", name="legacy /chatbot/ask")
    hits = search_help(request.question, 4)
    ctx = ToolContext(db=None, user=current_user)
    answer = answer_from_help(request.question, ctx, hits)["answer"]
    sources = [{"title": h["title"], "category": h.get("category") or "", "source": h.get("source")} for h in hits]
    trace_id = finish_trace(answer=answer)
    return ChatResponse(answer=answer, sources=sources, trace_id=trace_id)


@router.post("/agent", response_model=AgentResponse)
def chatbot_agent(
    request: AgentRequest,
    db: Optional[Session] = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """V3 Token-Optimized Agentic Chatbot Endpoint.

    Routes questions through:
      - Zero-Token handlers for Greeting/Navigation/WhoAmI/FAQ
      - Fast (8b) model for routing, table selection, summarization
      - Heavy (70b) model exclusively for SQL generation
    Returns action_buttons for clickable navigation in the frontend.
    """
    if not request.question.strip():
        return AgentResponse(
            answer="👋 Please type a question or say **menu** to see what I can help with!",
            action_buttons=[],
            tool_trace=[],
            iterations=0,
        )

    ctx = ToolContext(db=db, user=current_user, frontend_context=request.frontend_context)
    history = [t.model_dump() for t in (request.history or [])]

    start_trace(channel="chatbot", user=current_user, question=request.question)
    record("request", history_turns=len(history), has_page_context=request.frontend_context is not None)
    try:
        result = run_agent(question=request.question, history=history, ctx=ctx)
    except Exception as exc:
        record("error", where="run_agent", error=f"{type(exc).__name__}: {exc}")
        finish_trace(answer="", status="error")
        raise

    # Normalize tool_trace: ensure args is always a dict
    clean_trace = []
    for item in result.get("tool_trace", []):
        clean_trace.append(
            ToolTraceItem(
                name=item.get("name", "unknown"),
                args=item.get("args") or {},
                result_preview=item.get("result_preview", ""),
            )
        )

    # Only in-app paths and copy actions reach the browser.
    clean_buttons = [ActionButton(**btn) for btn in sanitize_action_buttons(result.get("action_buttons"))]

    widget_type = result.get("widget_type")
    trace_id = finish_trace(
        answer=result.get("answer", ""),
        buttons=[b.path for b in clean_buttons],
        widget_type=widget_type,
    )
    return AgentResponse(
        answer=result.get("answer", "I'm sorry, I couldn't generate a response."),
        action_buttons=clean_buttons,
        tool_trace=clean_trace,
        iterations=result.get("iterations", 1),
        widget_type=widget_type if widget_type == "RECORD_SUMMARY" else None,
        widget_data=result.get("widget_data") if widget_type == "RECORD_SUMMARY" else None,
        trace_id=trace_id,
    )


# ─── Audit traces ─────────────────────────────────────────────────────────────

def _trace_visible(row, current_user) -> bool:
    """Owners see their own traces, admins those of their active warehouse,
    super admins every trace."""
    if is_super_admin(current_user):
        return True
    if str(row["user_id"]) == str(getattr(current_user, "id", "")):
        return True
    if is_admin_role(current_user):
        wh_id = scoped_warehouse_id(current_user)
        return bool(wh_id) and str(row["warehouse_id"]) == wh_id
    return False


def _trace_out(row) -> dict:
    return {
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
        "steps": row["steps"],
    }


_TRACE_COLUMNS = ("id, created_at, channel, user_id, role, warehouse_id, question, intent, "
                  "answer, status, duration_ms, steps")


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db), current_user: object = Depends(get_current_user)):
    """How one answer was produced: every routing, retrieval, model, SQL and
    action step, in order. 404 for an unknown id or one outside the caller's
    scope."""
    try:
        trace_uuid = str(uuid.UUID(trace_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Trace not found")
    row = db.execute(text(f"SELECT {_TRACE_COLUMNS} FROM ai_traces WHERE id = CAST(:id AS uuid)"),
                     {"id": trace_uuid}).mappings().first()
    if row is None or not _trace_visible(row, current_user):
        raise HTTPException(status_code=404, detail="Trace not found")
    return _trace_out(row)


@router.get("/traces")
def list_traces(
    user_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None, pattern="^(chatbot|report)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """Recent traces, newest first. Users get their own; admins their active
    warehouse's (optionally one user's); super admins any."""
    clauses, params = [], {"limit": limit}
    if is_super_admin(current_user):
        pass
    elif is_admin_role(current_user):
        clauses.append("warehouse_id = CAST(:wh AS uuid)")
        params["wh"] = scoped_warehouse_id(current_user) or "00000000-0000-0000-0000-000000000000"
    else:
        clauses.append("user_id = CAST(:me AS uuid)")
        params["me"] = str(current_user.id)
    if user_id:
        try:
            params["uid"] = str(uuid.UUID(user_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="user_id must be a UUID")
        clauses.append("user_id = CAST(:uid AS uuid)")
    if channel:
        clauses.append("channel = :channel")
        params["channel"] = channel
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(
        f"SELECT {_TRACE_COLUMNS} FROM ai_traces {where} ORDER BY created_at DESC LIMIT :limit"
    ), params).mappings().all()
    return [{k: v for k, v in _trace_out(r).items() if k != "steps"} for r in rows]
