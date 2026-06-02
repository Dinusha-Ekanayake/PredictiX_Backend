"""SQLAlchemy engine and session factory.

DATABASE_URL is read from .env. If not set, it is constructed from
DATABASE_PASSWORD and PROJECT_REF (Supabase Postgres pooler connection).
"""
import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# override=True so the project's .env is authoritative even when a stale
# DATABASE_URL is already exported in the launching shell's environment.
load_dotenv(override=True)

logger = logging.getLogger(__name__)

_password = os.getenv("DATABASE_PASSWORD")
_project_ref = os.getenv("PROJECT_REF")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg2://postgres.{_project_ref}:{_password}@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres"
    if _password and _project_ref else None,
)

if DATABASE_URL:
    _safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    logger.info("[DB] Connecting to: %s", _safe_url)
else:
    logger.error("[DB] DATABASE_URL is not set — check your .env file")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
