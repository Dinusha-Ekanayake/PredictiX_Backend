"""Turning unexpected exceptions into safe HTTP errors.

An exception's text can carry SQL, connection strings, file paths or a model
provider's raw reply. It is logged with the full traceback for operators and
never sent to the client, which only receives the fixed message given here.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.exc import InterfaceError, OperationalError

log = logging.getLogger("predictix.errors")

DB_UNAVAILABLE = "Database temporarily unavailable. Please try again shortly."


def internal_error(message: str, exc: BaseException, status_code: int = 500) -> HTTPException:
    """Log `exc` with its traceback and return an HTTPException carrying only `message`.

    A dropped or refused database connection is reported as a 503 with the
    same message the app-wide handler in main.py uses, because it is a
    transient outage rather than a fault in the request.

    Usage: ``raise internal_error("Summary generation failed.", exc) from exc``
    """
    if isinstance(exc, (OperationalError, InterfaceError)):
        log.error("%s Database connection failed: %s", message, exc)
        return HTTPException(status_code=503, detail=DB_UNAVAILABLE)
    log.error("%s (%s: %s)", message, type(exc).__name__, exc, exc_info=exc)
    return HTTPException(status_code=status_code, detail=message)
