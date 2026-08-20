import os
import sys
from datetime import datetime

sys.path.insert(0, r"D:\Project\sharada-user-section-backend")
os.chdir(r"D:\Project\sharada-user-section-backend")
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    from app.db.session import SessionLocal
    from app.agents.report_agents import build_warehouse_context

    db = SessionLocal()
    warehouse_id = "c537c281-b6ad-4842-94ec-e937be0083e5"
    
    print(f"Testing build_warehouse_context for {warehouse_id}...")
    context = build_warehouse_context(db, warehouse_id)
    
    print("SUCCESS!")
    print(f"Total Assets: {context['total_assets']}")
    print(f"Total Tickets: {context['total_tickets']}")
    print(f"Est Cost LKR: {context['total_estimated_cost']}")
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    if 'db' in locals():
        db.close()
