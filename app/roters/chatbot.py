from fastapi import APIRouter
from pydantic import BaseModel
from app.ai.services.knowledge_service import search_knowledge
from app.ai.services.llm_service import ask_llm

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    answer: str
    sources: list

@router.post("/ask", response_model=ChatResponse)
def ask_question(request: ChatRequest):
    # Step 1: Search KB
    results = search_knowledge(request.question)

    # Step 2: Build context from KB results
    if results:
        context = "\n".join([
            f"- {item['title']}: {item['content']}"
            for item in results
        ])
    else:
        context = "No relevant knowledge found."

    # Step 3: Ask HuggingFace LLM
    answer = ask_llm(context, request.question)

    # Step 4: Return answer + sources
    sources = [{"title": r["title"], "category": r["category"]} for r in results]

    return ChatResponse(answer=answer, sources=sources)