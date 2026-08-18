import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    res = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_base';
    """)).fetchall()
    print('Columns in knowledge_base:')
    for r in res:
        print(f'- {r[0]}: {r[1]}')
except Exception as e:
    print('Failed:', e)
finally:
    db.close()
