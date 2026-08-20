import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile, Ticket
from app.ai.agent.tools import ToolContext
from app.ai.agent.agent_service import run_agent

db = SessionLocal()
try:
    user = db.query(Profile).filter(Profile.status == "active").first()
    ctx = ToolContext(db=db, user=user)
    
    query = "Show me the details of ticket T-0936."
    print("Testing run_agent for:", query)
    res = run_agent(query, history=[], ctx=ctx)
    print("\n--- Answer ---")
    print(res.get("answer"))
    print("\n--- Action Buttons ---")
    print(res.get("action_buttons"))
finally:
    db.close()
