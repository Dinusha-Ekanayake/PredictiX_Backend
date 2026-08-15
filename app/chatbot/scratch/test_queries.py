import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.ai.agent.tools import ToolContext, handle_database
from app.models import Profile

db = SessionLocal()
admin_user = db.query(Profile).filter(Profile.role.in_(["admin", "super_admin"])).first()
if not admin_user:
    class MockAdmin:
        id = "00000000-0000-0000-0000-000000000000"
        role = "admin"
        full_name = "Admin User"
        warehouse_id = None
    admin_user = MockAdmin()

ctx = ToolContext(db=db, user=admin_user)

questions = [
    "which is the most critical asset here",
    "how many tickets here",
    "give number of users, tickets, and assets by all sub categories",
]

for q in questions:
    print(f"\n==================== QUESTION: {q} ====================")
    try:
        res = handle_database(q, ctx)
        print("ANSWER:\n", res.get("answer"))
    except Exception as e:
        print("ERROR:", e)

db.close()
