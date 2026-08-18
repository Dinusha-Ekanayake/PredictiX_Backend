import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    print(conn.execute(text("SELECT SUM(p.estimated_cost_lkr) FROM pdm_batch_predictions p JOIN assets a ON p.asset_id = a.id WHERE a.warehouse_id = 'c537c281-b6ad-4842-94ec-e937be0083e5'")).scalar())
    print(conn.execute(text("SELECT SUM(p.estimated_cost_lkr) FROM pdm_batch_predictions p JOIN assets a ON p.asset_id = a.id WHERE a.warehouse_id = 'c537c281-b6ad-4842-94ec-e937be0083e5' AND p.maintenance_required = true")).scalar())
