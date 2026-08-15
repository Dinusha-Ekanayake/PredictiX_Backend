from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
res = db.execute(text("SELECT count(*), count(criticality_score), avg(criticality_score) FROM assets")).fetchall()
print("CRITICALITY SCORE:", res)

res = db.execute(text("SELECT count(*), count(health_score), avg(health_score) FROM pdm_batch_predictions")).fetchall()
print("PDM BATCH HEALTH SCORES:", res)

res = db.execute(text("SELECT count(*), count(health_score) FROM asset_failure_predictions")).fetchall()
print("ASSET FAILURE PREDICTIONS:", res)

db.close()
