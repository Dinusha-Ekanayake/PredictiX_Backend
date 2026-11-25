"""Account self-service: changing one's own password."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import Profile

log = logging.getLogger(__name__)

# 8 characters is the floor NIST SP 800-63B sets for user-chosen passwords.
MIN_PASSWORD_LENGTH = 8


class PasswordChangeRejected(Exception):
    """The change was refused; the message is safe to show the user."""


def change_password(db: Session, user_id: Any, current_password: str, new_password: str) -> None:
    """Replace the stored bcrypt hash after confirming the current password.

    Raises PasswordChangeRejected with a user-facing reason.
    """
    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        raise PasswordChangeRejected("This account's password cannot be changed here.")

    meta = dict(profile.meta) if isinstance(profile.meta, dict) else {}
    stored_hash = meta.get("password_hash") or ""
    if not stored_hash:
        raise PasswordChangeRejected("This account has no password yet. Ask an administrator to set one.")
    if not verify_password(current_password, stored_hash):
        raise PasswordChangeRejected("Current password is incorrect.")
    if new_password == current_password:
        raise PasswordChangeRejected("Choose a password different from the current one.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise PasswordChangeRejected(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if new_password.strip() != new_password or new_password.isdigit():
        raise PasswordChangeRejected("Passwords cannot start or end with spaces or be numbers only.")

    meta["password_hash"] = hash_password(new_password)
    profile.meta = meta
    try:
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Password change failed for %s", profile.id)
        raise
    log.info("Password changed for profile %s", str(profile.id)[:8])
