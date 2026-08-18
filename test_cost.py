import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    res = conn.execute(text('SELECT maintenance_required, COUNT(*), SUM(estimated_cost_lkr) FROM pdm_batch_predictions GROUP BY maintenance_required')).fetchall()
    print(res)
