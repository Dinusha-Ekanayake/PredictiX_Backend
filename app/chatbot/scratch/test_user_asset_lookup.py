import os
import re
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.models import Profile, Asset, Ticket, Warehouse, Department
from sqlalchemy import or_

db = SessionLocal()
try:
    print("Testing User Lookup for 'Ajith Bandara'...")
    query = 'give me details of user " Ajith Bandara"'
    clean_user = re.sub(r'^(give me|show me|details of|info on|about|user|profile of|\s|")+|"+$', '', query, flags=re.IGNORECASE).strip()
    print("Extracted user search term:", repr(clean_user))
    
    user = db.query(Profile).filter(
        or_(
            Profile.full_name.ilike(f"%{clean_user}%"),
            Profile.email.ilike(f"%{clean_user}%"),
            Profile.employee_id.ilike(f"%{clean_user}%")
        )
    ).first()
    
    if user:
        print(f"Found User: {user.full_name}, Email: {user.email}, Role: {user.role}, Status: {user.status}")
        
        # Check assigned assets
        assets = db.query(Asset).filter(Asset.assigned_to == user.id).all()
        print(f"Assigned Assets count: {len(assets)}")
        for a in assets:
            print(f"  - {a.asset_name} ({a.asset_code}) - {a.status}")
            
        # Check assigned tickets
        tickets = db.query(Ticket).filter(Ticket.assigned_to == user.id).all()
        print(f"Assigned Tickets count: {len(tickets)}")
        for t in tickets:
            print(f"  - {t.ticket_number}: {t.title} ({t.priority})")
    else:
        print("User not found by exact term. Listing sample users:")
        for u in db.query(Profile).limit(5).all():
            print(f"  - {u.full_name} ({u.email})")

    print("\nTesting Asset Lookup for 'Heli CPCD25' or 'LLX-COL-0004'...")
    asset_ref = "LLX-COL-0004"
    asset = db.query(Asset).filter(
        or_(
            Asset.asset_code.ilike(f"%{asset_ref}%"),
            Asset.asset_name.ilike(f"%{asset_ref}%"),
            Asset.registration_number.ilike(f"%{asset_ref}%")
        )
    ).first()
    if asset:
        print(f"Found Asset: {asset.asset_name} ({asset.asset_code}), Status: {asset.status}, Category: {asset.category}")
finally:
    db.close()
