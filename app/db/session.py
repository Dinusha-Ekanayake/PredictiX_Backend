"""SQLAlchemy engine and session factory.

DATABASE_URL is read from .env. If not set, it is constructed from
DATABASE_PASSWORD and PROJECT_REF (Supabase Postgres direct connection).
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

_password = os.getenv("DATABASE_PASSWORD")
_project_ref = os.getenv("PROJECT_REF")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://postgres:{_password}@db.{_project_ref}.supabase.co:5432/postgres"
    if _password and _project_ref else None,
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
