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

_POOLER_PORT = os.getenv("SUPABASE_POOLER_PORT", "5432")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Defaults to the session-mode pooler (5432). See the note by the engine
    # below for when to move to transaction mode (6543).
    f"postgresql+psycopg2://postgres.{_project_ref}:{_password}"
    f"@aws-1-ap-southeast-2.pooler.supabase.com:{_POOLER_PORT}/postgres"
    if _password and _project_ref else None,
)

if DATABASE_URL:
    _safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    logger.info("[DB] Connecting to: %s", _safe_url)
else:
    logger.error("[DB] DATABASE_URL is not set — check your .env file")

def _int_env(name: str, default: int) -> int:
    """Read a positive integer setting, falling back on anything unparseable."""
    try:
        value = int(os.getenv(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


# Supabase exposes two poolers, and which one is in DATABASE_URL decides how
# many connections this process may safely hold:
#
#   5432  session mode      one server connection per client for the whole
#                           session. This tier caps total clients at 15 across
#                           *every* process touching the database, so a dev
#                           server, a deployed instance and a test run together
#                           exhaust it and every request then fails with
#                           "max clients reached in session mode".
#
#   6543  transaction mode  the connection returns to the pooler after each
#                           transaction, so the client cap stops being the
#                           binding constraint. Measured cost: a warm request
#                           is roughly 200ms slower than session mode, and the
#                           first connection on each pool slot pays a one-off
#                           multi-second handshake.
#
# Session mode remains the default because it is faster per request. Switch the
# port in DATABASE_URL to 6543 when several processes need the database at once,
# which is the situation that produces the error above.
_is_transaction_pooler = ":6543" in (DATABASE_URL or "")

# Total connections this process may open is pool_size + max_overflow. Keep the
# session-mode default well under the 15-client cap so more than one process
# can run at a time; both are overridable for a deployment that owns the tier.
_default_pool = 3 if not _is_transaction_pooler else 5
_default_overflow = 2 if not _is_transaction_pooler else 5

POOL_SIZE = _int_env("DB_POOL_SIZE", _default_pool)
MAX_OVERFLOW = _int_env("DB_MAX_OVERFLOW", _default_overflow)

logger.info(
    "[DB] %s-mode pooler, up to %d connections from this process",
    "transaction" if _is_transaction_pooler else "session",
    POOL_SIZE + MAX_OVERFLOW,
)

engine = create_engine(
    DATABASE_URL,
    # Guards against handing out a connection the pooler has already dropped.
    # Costs one round-trip per checkout, which is the right trade on a
    # cross-region link where a stale connection surfaces as a 500.
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10},
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=10,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
