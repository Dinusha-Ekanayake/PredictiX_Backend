import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    res = conn.execute(text('''
        SELECT a.warehouse_id, COUNT(p.id) as required_assets, SUM(p.estimated_cost_lkr) as total_cost
        FROM pdm_batch_predictions p
        JOIN assets a ON p.asset_id = a.id
        WHERE p.status = 'ok' AND p.maintenance_required = true
        GROUP BY a.warehouse_id
    ''')).fetchall()
    
    for row in res:
        print(f"Warehouse ID: {row[0]}")
        print(f"Assets Needing Maintenance: {row[1]}")
        print(f"Estimated Cost: LKR {row[2]:,.2f}")
