import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    res = conn.execute(text("SELECT COALESCE(SUM(estimated_cost_lkr), 0) FROM pdm_batch_predictions WHERE status = 'ok'")).fetchone()
    print("Global Cost (unfiltered):", res)
    
    res2 = conn.execute(text("SELECT COALESCE(SUM(estimated_cost_lkr), 0) FROM pdm_batch_predictions WHERE status = 'ok' AND health_score < 60")).fetchone()
    print("Cost (health < 60):", res2)
    
    res3 = conn.execute(text("SELECT COALESCE(SUM(estimated_cost_lkr), 0) FROM pdm_batch_predictions WHERE status = 'ok' AND predicted_days_until_maintenance <= 30")).fetchone()
    print("Cost (maintenance <= 30d):", res3)
