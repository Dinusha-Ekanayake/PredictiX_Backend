from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
res = db.execute(text("SELECT warehouse_id, count(*) FROM assets GROUP BY warehouse_id")).fetchall()
print("ASSET WAREHOUSE IDS:", res)

res = db.execute(text("SELECT id, name, code FROM warehouses")).fetchall()
print("WAREHOUSES:", res)

res = db.execute(text("SELECT warehouse_id, role, count(*) FROM profiles GROUP BY warehouse_id, role")).fetchall()
print("PROFILE WAREHOUSE IDS:", res)

db.close()
