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

    active_warehouse_id = payload.get("active_warehouse_id")

    from app.models import Profile  # local import to avoid circular deps

    if db is not None:
        user = db.query(Profile).filter(Profile.id == user_id).first()
        if user:
            # Dynamically attach the session's active warehouse
            setattr(user, "active_warehouse_id", active_warehouse_id)
            return user
        else:
            # No DB row — build a lightweight in-memory stub for demo / super-admin accounts
            email = payload.get("email", "")
            role = payload.get("role", "user")
            stub = Profile(
                id=user_id,
                email=email,
                full_name=email.split("@")[0].replace(".", " ").title(),
                role=role,
                status="active",
                warehouse_id=None,
                department_id=None,
                meta={},
            )
            setattr(stub, "active_warehouse_id", active_warehouse_id)
            return stub
    else:
        raise HTTPException(status_code=500, detail="Database connection missing")
