import os
import traceback
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile
from app.ai.agent.tools import ToolContext
from app.ai.agent.actions.insert_actions import handle_action

db = SessionLocal()
try:
    user = db.query(Profile).filter(Profile.email == "aroshnimantha386@gmail.com").first()
    if not user:
        user = db.query(Profile).first()
    print(f"Testing with user: {user.full_name}, ID: {user.id}, Role: {user.role}, Warehouse: {user.warehouse_id}")
    
    ctx = ToolContext(db=db, user=user)
    query = "Create a high priority ticket for Forklift FL-04 titled 'Brake pressure loss' with description 'Operator reported low hydraulic pressure during transit."
    
    print("\nRunning handle_action...")
    res = handle_action(query, ctx)
    print("handle_action Result:", res)
except Exception as e:
    print("Exception occurred:")
    traceback.print_exc()
finally:
    db.close()
