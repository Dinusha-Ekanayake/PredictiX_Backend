import os
from sqlalchemy import create_engine, text
from app.db.session import engine
from app.models import KBDocument
from app.db import Base

with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

KBDocument.__table__.create(engine, checkfirst=True)
print("Table created successfully!")
