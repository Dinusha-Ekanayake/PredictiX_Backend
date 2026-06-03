"""Database package.

Re-exports the canonical SQLAlchemy primitives so callers can use either:
    from app.db import Base, SessionLocal, engine
    from app.db.session import SessionLocal
    from app.db.base import Base
"""
from .base import Base
from .session import SessionLocal, engine, DATABASE_URL

__all__ = ["Base", "SessionLocal", "engine", "DATABASE_URL"]






# .ok now it's time for this too. let's choose best model properly by comparing. give me the updated .ipynb file as predictix_pm_model_v4-classifier
