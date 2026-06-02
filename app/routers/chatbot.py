from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext
from app.ai.services.knowledge_service import search_knowledge
from app.ai.services.llm_service import ask_llm
from app.deps import get_current_user, get_db

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])


# ─── Legacy: simple knowledge-base RAG (no agent, no auth) ────────────────────


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    sources: list


@router.post("/ask", response_model=ChatResponse)
def ask_question(request: ChatRequest):
    """Legacy endpoint: simple RAG over the knowledge base. Kept for backwards compatibility."""
    results = search_knowledge(request.question)

    context = (
        "\n".join(f"- {r['title']}: {r['content']}" for r in results)
        if results
        else "No relevant knowledge found in the system."
    )

    answer = ask_llm(context, request.question)
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
    args: dict
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
