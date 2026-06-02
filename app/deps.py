"""FastAPI dependencies: database session and current-user resolution."""
import logging
import os
from typing import Generator, Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.db import SessionLocal

log = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Optional[Session], None, None]:
    """Yield a SQLAlchemy session, or None if the DB is not configured.

    Returning None keeps dev environments without a DB password from
    hanging on connection timeout; routers must handle the None case.
    """
    if not os.getenv("DATABASE_PASSWORD") and not os.getenv("DATABASE_URL"):
        yield None
        return

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Optional[Session] = Depends(get_db),
):
    """Decode JWT and return the matching Profile.

    Falls back to a lightweight in-memory profile when the DB row is
    missing — supports development logins for accounts that exist in
    auth's TEST_USERS but not yet in the profiles table.
    """
    try:
        payload = jwt.decode(
            token,
            os.getenv("JWT_SECRET", "supersecret"),
            algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
        )
    except JWTError as exc:
        log.warning("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    from app.models import Profile  # local import to avoid circular deps

    if db is not None:
        user = db.query(Profile).filter(Profile.id == user_id).first()
        if user:
            return user

    return _build_mock_profile(
        user_id=user_id,
        email=payload.get("email", "test@example.com"),
        role=payload.get("role", "user"),
        db=db,
    )


def _build_mock_profile(*, user_id: str, email: str, role: str, db: Optional[Session]):
    """Construct a duck-typed Profile when the DB record is missing."""
    from app.models import Department

    department_id = None
    if db is not None:
        keyword_to_dept = {
            "transportation": "Transportation",
            "electrical": "Electrical",
            "software": "Software",
            "mechanical": "Mechanical",
        }
        dept_name = next(
            (name for kw, name in keyword_to_dept.items() if kw in email.lower()),
            "Transportation",
        )
        dept = db.query(Department).filter(Department.name == dept_name).first()
        if dept:
            department_id = dept.id

    class MockProfile:
        def __init__(self) -> None:
            self.id = user_id
            self.email = email
            self.role = role
            self.full_name = email.split("@")[0].replace(".", " ").title()
            self.phone = None
            self.status = "active"
            self.warehouse_id = None
            self.department_id = department_id
            self.meta = {}
            self.employee_id = f"EMP-{user_id[:8]}"

    return MockProfile()
