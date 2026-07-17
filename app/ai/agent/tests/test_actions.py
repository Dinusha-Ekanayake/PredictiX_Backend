import asyncio
import json
import uuid
from app.db.session import SessionLocal
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
        user=MockUser(id="11111111-1111-1111-1111-111111111111", role="admin", full_name="Admin User", warehouse_id="33333333-3333-3333-3333-333333333333")
    )
    
    # Mock Standard User Context
    user_ctx = ToolContext(
        db=db,
        user=MockUser(id="22222222-2222-2222-2222-222222222222", role="user", full_name="Standard User", warehouse_id="33333333-3333-3333-3333-333333333333")
    )

    tests = [
        {"q": "Create a high priority ticket for broken forklift", "ctx": user_ctx, "desc": "User creates ticket (Allowed)"},
        {"q": "Add a new asset named Truck A-10", "ctx": user_ctx, "desc": "User creates asset (Denied)"},
        {"q": "Insert a new asset named Truck A-10", "ctx": admin_ctx, "desc": "Admin creates asset (Allowed)"},
        {"q": "Delete ticket #12", "ctx": admin_ctx, "desc": "Admin tries to delete (Denied)"}
    ]

    for t in tests:
        try:
            res = run_agent(t["q"], [], t["ctx"])
            ans = res.get("answer", "").strip().replace("\n", " ")
            r = {"test": t["desc"], "question": t["q"], "answer": ans}
            print(json.dumps(r))
        except Exception as e:
            r = {"test": t["desc"], "question": t["q"], "error": str(e)}
            print(json.dumps(r))

    print("DONE")
    db.rollback()

if __name__ == "__main__":
    run_tests()
