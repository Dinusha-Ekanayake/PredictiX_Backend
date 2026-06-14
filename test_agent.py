import asyncio
from app.db import SessionLocal
from app.models import Profile
from app.ai.agent.agent_service import run_agent
from app.ai.agent.tools import ToolContext

def test():
    db = SessionLocal()
    user = db.query(Profile).filter(Profile.role == 'superadmin').first()
    if not user:
        print("No superadmin found. Using any user.")
        user = db.query(Profile).first()
        
    ctx = ToolContext(db=db, user=user)
    print(f"Testing with user: {user.full_name} ({user.role})")
    
    res, trace = run_agent('how many open tickets are there?', ctx)
    print('Answer:', res)
    print('Trace:', [t["name"] for t in trace])

if __name__ == "__main__":
    test()
