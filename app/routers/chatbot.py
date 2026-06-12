"""Chatbot router — legacy RAG + agentic tool-calling endpoints."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext
from app.ai.services.knowledge_service import search_knowledge
from app.ai.services.llm_service import ask_llm
from app.core.toon import to_toon
from app.deps import get_current_user, get_db
from app.models import Asset, Profile, Ticket, Warehouse

log = logging.getLogger("predictix.chatbot")

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


# ─── DB Context Builder ──────────────────────────────────────────────────────
# Queries the REAL database tables so the LLM has accurate numbers
# (tickets, assets, users, warehouses) — not just the knowledge base.


def _build_db_context(db: Session) -> str:
    """Build a plain-text data snapshot from the live database.

    This gives the LLM accurate numbers that match the website dashboard.
    """
    lines: list[str] = []
    lines.append("=== LIVE SYSTEM DATA (accurate, from the database) ===")

    # ── Ticket stats ──────────────────────────────────────────────────────
    try:
        total_tickets = db.query(sa_func.count(Ticket.id)).scalar() or 0
        lines.append(f"\nTICKETS (total: {total_tickets})")

        # By status
        status_rows = (
            db.query(Ticket.status, sa_func.count(Ticket.id))
            .group_by(Ticket.status)
            .all()
        )
        if status_rows:
            lines.append("  By status:")
            for status_val, cnt in status_rows:
                label = status_val.value if hasattr(status_val, "value") else str(status_val)
                lines.append(f"    {label}: {cnt}")

        # By priority
        priority_rows = (
            db.query(Ticket.priority, sa_func.count(Ticket.id))
            .filter(Ticket.priority.isnot(None))
            .group_by(Ticket.priority)
            .all()
        )
        if priority_rows:
            lines.append("  By priority:")
            for pri_val, cnt in priority_rows:
                label = pri_val.value if hasattr(pri_val, "value") else str(pri_val)
                lines.append(f"    {label}: {cnt}")

        # By category (final_category)
        cat_rows = (
            db.query(Ticket.final_category, sa_func.count(Ticket.id))
            .filter(Ticket.final_category.isnot(None))
            .group_by(Ticket.final_category)
            .all()
        )
        if cat_rows:
            lines.append("  By category:")
            for cat_val, cnt in cat_rows:
                label = cat_val.value if hasattr(cat_val, "value") else str(cat_val)
                lines.append(f"    {label}: {cnt}")

        # Recent tickets (last 5)
        recent = (
            db.query(Ticket.ticket_number, Ticket.title, Ticket.status, Ticket.priority)
            .order_by(Ticket.created_at.desc())
            .limit(5)
            .all()
        )
        if recent:
            lines.append("  Recent tickets:")
            for tn, title, st, pri in recent:
                st_label = st.value if hasattr(st, "value") else str(st)
                pri_label = (pri.value if hasattr(pri, "value") else str(pri)) if pri else "none"
                lines.append(f"    {tn} | {title} | status={st_label} | priority={pri_label}")
    except Exception as e:
        log.warning("Failed to query ticket stats: %s", e)
        lines.append("  (ticket data unavailable)")

    # ── Asset stats ───────────────────────────────────────────────────────
    try:
        total_assets = db.query(sa_func.count(Asset.id)).scalar() or 0
        lines.append(f"\nASSETS (total: {total_assets})")

        asset_status_rows = (
            db.query(Asset.status, sa_func.count(Asset.id))
            .group_by(Asset.status)
            .all()
        )
        if asset_status_rows:
            lines.append("  By status:")
            for st, cnt in asset_status_rows:
                lines.append(f"    {st}: {cnt}")

        # By type
        asset_type_rows = (
            db.query(Asset.asset_type, sa_func.count(Asset.id))
            .group_by(Asset.asset_type)
            .all()
        )
        if asset_type_rows:
            lines.append("  By type:")
            for atype, cnt in asset_type_rows:
                lines.append(f"    {atype}: {cnt}")
    except Exception as e:
        log.warning("Failed to query asset stats: %s", e)
        lines.append("  (asset data unavailable)")

    # ── User stats ────────────────────────────────────────────────────────
    try:
        total_users = db.query(sa_func.count(Profile.id)).scalar() or 0
        lines.append(f"\nUSERS (total: {total_users})")

        role_rows = (
            db.query(Profile.role, sa_func.count(Profile.id))
            .group_by(Profile.role)
            .all()
        )
        if role_rows:
            lines.append("  By role:")
            for role, cnt in role_rows:
                lines.append(f"    {role}: {cnt}")
    except Exception as e:
        log.warning("Failed to query user stats: %s", e)
        lines.append("  (user data unavailable)")

    # ── Warehouse stats ───────────────────────────────────────────────────
    try:
        warehouses = (
            db.query(Warehouse.name, Warehouse.city, Warehouse.is_active)
            .order_by(Warehouse.name)
            .all()
        )
        lines.append(f"\nWAREHOUSES (total: {len(warehouses)})")
        for wh_name, city, active in warehouses:
            status = "active" if active else "inactive"
            lines.append(f"  - {wh_name} ({city}) [{status}]")
    except Exception as e:
        log.warning("Failed to query warehouse stats: %s", e)
        lines.append("  (warehouse data unavailable)")

    lines.append("\n=== END LIVE SYSTEM DATA ===")
    return "\n".join(lines)


# ─── Legacy: knowledge-base RAG + live DB context ─────────────────────────────


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list


@router.post("/ask", response_model=ChatResponse)
def ask_question(
    request: ChatRequest,
    db: Optional[Session] = Depends(get_db),
):
    """RAG endpoint: answers from the knowledge base PLUS real database stats.

    Enriches the LLM context with live ticket/asset/user/warehouse counts
    so answers match the website exactly.
    """
    # 1. Build live DB context (accurate numbers)
    db_context = ""
    if db is not None:
        try:
            db_context = _build_db_context(db)
        except Exception as e:
            log.warning("_build_db_context failed: %s", e)
            db_context = "(Live database stats are temporarily unavailable.)"

    # 2. Knowledge base search (supplementary info)
    results = search_knowledge(request.question)
    knowledge_context = ""
    if results:
        knowledge_context = "\n=== KNOWLEDGE BASE ===\n"
        knowledge_context += "\n".join(
            f"- {r['title']}: {r['content']}" for r in results
        )
        knowledge_context += "\n=== END KNOWLEDGE BASE ==="

    # 3. Combine both into one context
    combined_context = db_context
    if knowledge_context:
        combined_context += "\n\n" + knowledge_context
    if not combined_context.strip():
        combined_context = "No relevant data found in the system."

    # 4. Ask the LLM with enriched context
    answer = ask_llm(combined_context, request.question)
    sources = [{"title": r["title"], "category": r["category"]} for r in results]
    return ChatResponse(answer=answer, sources=sources)


# ─── Agentic: tool-calling chatbot ────────────────────────────────────────────


class ChatHistoryTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AgentRequest(BaseModel):
    question: str
    history: Optional[list[ChatHistoryTurn]] = None


class ToolTraceItem(BaseModel):
    name: str
    args: Optional[dict] = None
    result_preview: str


class AgentResponse(BaseModel):
    answer: str
    tool_trace: list[ToolTraceItem]
    iterations: int


@router.post("/agent", response_model=AgentResponse)
def chatbot_agent(
    request: AgentRequest,
    db: Optional[Session] = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """Agentic chatbot endpoint.

    The LLM (Groq llama-3.3-70b) is given access to read-only tools
    (list_tickets, list_assets, predict_failure, etc.) and decides which
    to call to answer the user's question. Every tool runs with the
    current user's role/identity, so role-based scoping is enforced.
    """
    if not request.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")

    ctx = ToolContext(db=db, user=current_user)
    history = [t.model_dump() for t in (request.history or [])]

    result = run_agent(question=request.question, history=history, ctx=ctx)
    return AgentResponse(**result)
