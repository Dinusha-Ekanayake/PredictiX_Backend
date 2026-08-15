from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
print("=== ASSET STATUSES ===")
res = db.execute(text("SELECT status, count(*) FROM assets GROUP BY status")).fetchall()
print(res)

print("=== ASSET HEALTH BANDS ===")
res = db.execute(text("SELECT health_band, count(*) FROM assets GROUP BY health_band")).fetchall()
print(res)

print("=== PDM BATCH PREDICTIONS RISK LEVELS ===")
res = db.execute(text("SELECT risk_level, health_status, count(*) FROM pdm_batch_predictions GROUP BY risk_level, health_status")).fetchall()
print(res)

print("=== TICKET STATUSES ===")
res = db.execute(text("SELECT status, count(*) FROM tickets GROUP BY status")).fetchall()
print(res)

print("=== TICKET PRIORITIES ===")
res = db.execute(text("SELECT priority, count(*) FROM tickets GROUP BY priority")).fetchall()
print(res)

print("=== TICKET CATEGORIES ===")
res = db.execute(text("SELECT predicted_category, final_category, count(*) FROM tickets GROUP BY predicted_category, final_category")).fetchall()
print(res)

print("=== USER ROLES ===")
res = db.execute(text("SELECT role, status, count(*) FROM profiles GROUP BY role, status")).fetchall()
print(res)

db.close()
