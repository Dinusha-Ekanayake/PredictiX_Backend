"""PredictiX Chatbot Router – V3 (Token-Optimized, Action-Button enabled)."""
from __future__ import annotations

from typing import Any, Optional, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext
from app.ai.services.knowledge_service import search_knowledge
from app.ai.services.llm_service import ask_llm
from app.deps import get_current_user, get_db, require_user

# Every endpoint here spends Groq quota on the caller's behalf, so a valid token
# is required at the router level. /ask previously had no auth dependency at
# all: an anonymous POST to the public URL returned a real model answer, and
# with no rate limiting anywhere in the application that is an open tap on a
# paid API. The frontend already sends a token on the endpoint it actually uses
# (/agent), so this closes the hole without changing any working call.
router = APIRouter(
    prefix="/chatbot",
    tags=["Chatbot"],
    dependencies=[Depends(require_user)],
)


# ─── Models ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Any] = []


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
    question: str
    history: Optional[list[ChatHistoryTurn]] = None
    frontend_context: Optional[dict] = None


class AgentResponse(BaseModel):
    answer: str
    action_buttons: list[ActionButton] = []
    tool_trace: list[ToolTraceItem] = []
    iterations: int = 1
    widget_type: Optional[str] = None
    widget_data: Optional[Dict[str, Any]] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=ChatResponse, deprecated=True)
def ask_question(request: ChatRequest):
    """Legacy RAG endpoint — kept for backwards compatibility only.
    The main chatbot should use /chatbot/agent instead.

    Marked deprecated to match reality: the only frontend helper that targets
    this path (askChatbot in lib/apiClient.ts) is not called by any component,
    and it sends no Authorization header — so it would now fail. Every chat
    surface in the product goes through /chatbot/agent.
    """
    results = search_knowledge(request.question)
    context = (
        "\n".join(f"- {r['title']}: {r['content']}" for r in results)
        if results
        else "No relevant knowledge found in the system."
    )
    answer = ask_llm(context, request.question)
    sources = [{"title": r["title"], "category": r.get("category", "")} for r in results]
    return ChatResponse(answer=answer, sources=sources)


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

    result = run_agent(question=request.question, history=history, ctx=ctx)

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

    # Normalize action_buttons
    clean_buttons = []
    for btn in result.get("action_buttons", []):
        clean_buttons.append(ActionButton(label=btn.get("label", "Go"), path=btn.get("path", "/")))

    return AgentResponse(
        answer=result.get("answer", "I'm sorry, I couldn't generate a response."),
        action_buttons=clean_buttons,
        tool_trace=clean_trace,
        iterations=result.get("iterations", 1),
    )
