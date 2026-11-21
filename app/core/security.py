"""Password hashing and JWT helpers.

Hashes are standard bcrypt ($2a$/$2b$), so hashes written by the previous
passlib-based code verify unchanged.
"""
from __future__ import annotations

import bcrypt
import jwt

from app.core.config import jwt_algorithm, jwt_secret

# bcrypt only reads the first 72 bytes of a password and the library raises on
# longer input, so longer passwords are cut to that length before hashing and
# verifying. Both sides cut the same way, so the result is unchanged.
_BCRYPT_MAX_BYTES = 72

# Errors a caller should treat as "not a valid token".
InvalidTokenError = jwt.PyJWTError


def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(_password_bytes(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def encode_token(payload: dict) -> str:
    return jwt.encode(payload, jwt_secret(), algorithm=jwt_algorithm())


def decode_token(token: str) -> dict:
    """Verify signature and expiry and return the claims.

    Raises InvalidTokenError on any problem with the token.
    """
    return jwt.decode(
        token,
        jwt_secret(),
        algorithms=[jwt_algorithm()],
        options={"require": ["exp", "sub"]},
    )
