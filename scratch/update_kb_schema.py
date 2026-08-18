import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    # Check if vector extension is enabled and vector exists
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
    
    # Alter table knowledge_base to add missing columns
    db.execute(text("""
        ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS tags text[];
        ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
        ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS created_by uuid;
        ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS updated_at timestamp without time zone;
    """))
    db.commit()
    print("Schema updated successfully!")
    
    # Inspect schema again
    res = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_base';
    """)).fetchall()
    print('Updated columns in knowledge_base:')
    for r in res:
        print(f'- {r[0]}: {r[1]}')
except Exception as e:
    db.rollback()
    print("Failed to update schema:", e)
finally:
    db.close()
