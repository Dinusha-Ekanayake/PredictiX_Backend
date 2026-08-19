import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile
from app.ai.agent.tools import ToolContext
from app.ai.agent.agent_service import run_agent

db = SessionLocal()
try:
    admin_user = db.query(Profile).filter(Profile.role == "super_admin").first()
    normal_user = db.query(Profile).filter(Profile.role == "user").first()
    
    print("--- 1. Admin querying User details for 'Ajith Bandara' ---")
    ctx_admin = ToolContext(db=db, user=admin_user)
    q1 = 'give me details of user " Ajith Bandara"'
    res1 = run_agent(q1, history=[], ctx=ctx_admin)
    print("ANSWER:\n" + res1.get("answer").encode('ascii', 'ignore').decode('ascii'))
    print("BUTTONS:", res1.get("action_buttons"))

    print("\n--- 2. Normal User querying User details for 'Ajith Bandara' (RBAC Test) ---")
    ctx_user = ToolContext(db=db, user=normal_user)
    res2 = run_agent(q1, history=[], ctx=ctx_user)
    print("ANSWER:\n" + res2.get("answer").encode('ascii', 'ignore').decode('ascii'))
    print("BUTTONS:", res2.get("action_buttons"))

    print("\n--- 3. Querying Asset details for 'LLX-COL-0004' / 'Heli CPCD25' ---")
    q3 = 'give me details of asset Heli CPCD25'
    res3 = run_agent(q3, history=[], ctx=ctx_admin)
    print("ANSWER:\n" + res3.get("answer").encode('ascii', 'ignore').decode('ascii'))
    print("BUTTONS:", res3.get("action_buttons"))

finally:
    db.close()
