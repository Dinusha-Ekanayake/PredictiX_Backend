"""Database package.

Re-exports the canonical SQLAlchemy primitives so callers can use either:
    from app.db import Base, SessionLocal, engine
    from app.db.session import SessionLocal
    from app.db.base import Base
"""
from .base import Base
from .session import SessionLocal, engine, DATABASE_URL

__all__ = ["Base", "SessionLocal", "engine", "DATABASE_URL"]
