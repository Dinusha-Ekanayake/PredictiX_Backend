from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv("D:\\Project\\sharada-user-section-backend\\.env")
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Query to get a count of tags to show variety
    print("--- ?? VECTOR DATABASE SUMMARY ---")
    
    count_res = conn.execute(text("SELECT count(*) FROM kb_documents"))
    print(f"Total Vector Chunks: {count_res.scalar()}")
    
    print("\n--- ?? SAMPLE DATA (First 2 chunks) ---")
    sample = conn.execute(text("SELECT id, tags, left(text, 150) as text_snippet FROM kb_documents LIMIT 2"))
    for row in sample:
        print(f"ID: {row[0]}")
        print(f"Tags: {row[1]}")
        print(f"Text Snippet: {row[2]}...\n")
