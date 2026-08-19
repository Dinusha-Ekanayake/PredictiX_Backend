import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile, Ticket, Asset
from app.ai.agent.tools import ToolContext
from app.ai.agent.actions.insert_actions import handle_action

db = SessionLocal()
try:
    user = db.query(Profile).filter(Profile.email == "aroshnimantha386@gmail.com").first()
    if not user:
        user = db.query(Profile).first()
    
    ctx = ToolContext(db=db, user=user)
    query = "Create a high priority ticket for Forklift FL-04 titled 'Brake pressure loss' with description 'Operator reported low hydraulic pressure during transit."
    
    print("Testing updated handle_action...")
    res = handle_action(query, ctx)
    print("handle_action Answer:\n", res.get("answer"))
    print("Action Buttons:\n", res.get("action_buttons"))
finally:
    db.close()
