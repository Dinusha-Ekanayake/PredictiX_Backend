from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()

def get_stats(is_admin=True, warehouse_id=None, user_id=None):
    # Tickets breakdown
    t_status = db.execute(text("SELECT status, count(*) FROM tickets GROUP BY status")).fetchall()
    t_priority = db.execute(text("SELECT priority, count(*) FROM tickets GROUP BY priority")).fetchall()
    t_category = db.execute(text("SELECT COALESCE(final_category, predicted_category, 'other'), count(*) FROM tickets GROUP BY COALESCE(final_category, predicted_category, 'other')")).fetchall()
    
    # Assets breakdown
    a_status = db.execute(text("SELECT status, count(*) FROM assets GROUP BY status")).fetchall()
    a_health = db.execute(text("SELECT health_band, count(*) FROM assets GROUP BY health_band")).fetchall()
    a_category = db.execute(text("SELECT category, count(*) FROM assets GROUP BY category")).fetchall()
    
    # Users breakdown
    u_role = db.execute(text("SELECT role, count(*) FROM profiles GROUP BY role")).fetchall()
    u_status = db.execute(text("SELECT status, count(*) FROM profiles GROUP BY status")).fetchall()
    
    print("TICKETS BY STATUS:", t_status)
    print("TICKETS BY PRIORITY:", t_priority)
    print("TICKETS BY CATEGORY:", t_category)
    print("ASSETS BY STATUS:", a_status)
    print("ASSETS BY HEALTH:", a_health)
    print("ASSETS BY CATEGORY:", a_category)
    print("USERS BY ROLE:", u_role)
    print("USERS BY STATUS:", u_status)

get_stats()
db.close()
