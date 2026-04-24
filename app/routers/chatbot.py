from fastapi import APIRouter
from app.schemas.chatbot import ChatRequest, ChatResponse
from app.ai.services.knowledge_service import search_knowledge
from app.ai.services.llm_service import ask_llm

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/ask", response_model=ChatResponse)
def ask_question(request: ChatRequest):
    # Step 1: Search knowledge base
    results = search_knowledge(request.question)

    # Step 2: Build context from results
    if results:
        context = "\n".join([
            f"- {item['title']}: {item['content']}"
            for item in results
        ])
    else:
        context = "No relevant knowledge found in the system."

    # Step 3: Get answer from Groq LLM
    answer = ask_llm(context, request.question)

    # Step 4: Build sources list
    sources = [
        {"title": r["title"], "category": r["category"]}
        for r in results
    ]

    return ChatResponse(answer=answer, sources=sources)
