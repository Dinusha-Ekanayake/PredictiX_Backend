import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.ai.agent.tools import ToolContext, handle_database

db = SessionLocal()

class MockAdmin:
    id = "11111111-1111-1111-1111-111111111111"
    role = "admin"
    full_name = "Admin User"
    warehouse_id = None

class MockUser:
    id = "22222222-2222-2222-2222-222222222222"
    role = "user"
    full_name = "Regular User"
    warehouse_id = None

admin_ctx = ToolContext(db=db, user=MockAdmin())
user_ctx = ToolContext(db=db, user=MockUser())

test_cases = [
    (admin_ctx, "which is the most critical asset here"),
    (admin_ctx, "how many tickets here"),
    (admin_ctx, "give number of users, tickets, and assets by all sub categories"),
    (user_ctx, "how many tickets here"),
    (user_ctx, "how many users here"),
]

for ctx, q in test_cases:
    print(f"\n=======================================================")
    print(f"ROLE: {ctx.role.upper()} | QUESTION: {q}")
    print("=======================================================")
    try:
        res = handle_database(q, ctx)
        ans = res.get("answer", "")
        # Use ascii representation for clean console display
        print(ans.encode("ascii", "backslashreplace").decode("ascii"))
    except Exception as e:
        print("ERROR:", e)

db.close()
