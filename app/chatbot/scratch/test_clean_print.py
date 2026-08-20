import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile
from app.ai.agent.tools import ToolContext
from app.ai.agent.agent_service import run_agent

db = SessionLocal()
try:
    user = db.query(Profile).filter(Profile.status == "active").first()
    ctx = ToolContext(db=db, user=user)
    
    query = "Show me the details of ticket T-0936."
    res = run_agent(query, history=[], ctx=ctx)
    print("OUTPUT ANSWER:\n" + res.get("answer").encode('ascii', 'ignore').decode('ascii'))
    print("ACTION BUTTONS:", res.get("action_buttons"))
finally:
    db.close()
