import asyncio
import json
import uuid
from app.db.session import SessionLocal
from app.ai.agent.agent_service import run_agent, _rewrite_query_with_history
from app.ai.agent.tools import ToolContext
import logging

logging.basicConfig(level=logging.ERROR)

def test_query_rewriting():
    history = [
        {"role": "user", "content": "Show me my open tickets"},
        {"role": "assistant", "content": "Here are your open tickets: 1. Broken HVAC (Ticket #101), 2. Flat tire (Ticket #102)"}
    ]
    question = "Mark the first one as resolved"
    
    rewritten = _rewrite_query_with_history(question, history)
    print(f"Original: {question}")
    print(f"Rewritten: {rewritten}")
    
    # Test 2
    history2 = [
        {"role": "user", "content": "Show me details for asset A-500"},
        {"role": "assistant", "content": "Asset A-500 is a Generator with 95% health."}
    ]
    q2 = "Is it currently active?"
    r2 = _rewrite_query_with_history(q2, history2)
    print(f"Original: {q2}")
    print(f"Rewritten: {r2}")

if __name__ == "__main__":
    test_query_rewriting()
