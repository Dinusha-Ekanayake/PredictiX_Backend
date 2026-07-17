import asyncio
import json
from app.db.session import SessionLocal
from app.models import Profile
from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext
import logging

logging.basicConfig(level=logging.ERROR)

class MockUser:
    def __init__(self, id, role, warehouse_id=None, full_name=None):
        self.id = id
        self.role = role
        self.warehouse_id = warehouse_id
        self.full_name = full_name

def run_tests():
    db = SessionLocal()
    
    # Mock Admin Context
    admin_ctx = ToolContext(
        db=db,
        user=MockUser(id="11111111-1111-1111-1111-111111111111", role="admin", full_name="Admin User")
    )
    
    # Mock Standard User Context
    user_ctx = ToolContext(
        db=db,
        user=MockUser(id="22222222-2222-2222-2222-222222222222", role="user", full_name="Standard User")
    )

    tests = [
        {"q": "Hello!", "ctx": admin_ctx, "desc": "Greeting (Admin)"},
        {"q": "Take me to my settings", "ctx": user_ctx, "desc": "Navigation (User)"},
        {"q": "What are the activities I can do as admin and user?", "ctx": user_ctx, "desc": "Role Question (LLM Fallback)"},
        {"q": "How many open tickets are there?", "ctx": admin_ctx, "desc": "Dashboard Stats (Admin)"},
        {"q": "How many open tickets are there?", "ctx": user_ctx, "desc": "Dashboard Stats (User - Should Deny)"},
        {"q": "Show me assets with status active", "ctx": user_ctx, "desc": "Custom SQL Query (User - Should Scope to User)"}
    ]

    results = []
    
    for t in tests:
        try:
            res = run_agent(t["q"], [], t["ctx"])
            ans = res.get("answer", "").strip().replace("\n", " ")
            r = {"test": t["desc"], "question": t["q"], "answer": ans, "status": "Success"}
            results.append(r)
            print(json.dumps(r))
        except Exception as e:
            r = {"test": t["desc"], "question": t["q"], "answer": str(e), "status": "Error"}
            results.append(r)
            print(json.dumps(r))

    print("DONE")

if __name__ == "__main__":
    run_tests()
