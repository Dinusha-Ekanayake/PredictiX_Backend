import os

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    # Lifetime of an access token. The frontend has no refresh flow, so this is
    # also the longest a session lasts before the user signs in again.
    ACCESS_TOKEN_TTL_MINUTES: int = 480

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().strip('"').strip("'").lower() in {"1", "true", "yes", "on"}


def access_token_ttl_minutes() -> int:
    """Access-token lifetime in minutes, read from ACCESS_TOKEN_TTL_MINUTES."""
    raw = os.getenv("ACCESS_TOKEN_TTL_MINUTES")
    try:
        value = int(raw) if raw and raw.strip() else settings.ACCESS_TOKEN_TTL_MINUTES
    except ValueError:
        value = settings.ACCESS_TOKEN_TTL_MINUTES
    return value if value > 0 else 480


def demo_accounts_enabled() -> bool:
    """Whether the built-in demo logins in app/routers/auth.py are accepted.

    They have public passwords and no database row, so production should set
    ENABLE_DEMO_ACCOUNTS=false once demos are no longer needed.
    """
    return _env_flag("ENABLE_DEMO_ACCOUNTS", True)


def scheduler_enabled() -> bool:
    """Whether this process runs the background jobs (PdM batch, reminders).

    Every process that runs them writes to the same database, so only the
    deployed API should. Local dev servers and CI set SCHEDULER_ENABLED=false.
    """
    return _env_flag("SCHEDULER_ENABLED", True)


def jwt_secret() -> str:
    """Return the JWT signing secret, failing fast if it is not configured.

    Reads the live environment first (so a value injected at deploy time on
    EC2/Vercel is honoured even if it differs from the .env baked at import),
    then falls back to the validated Settings value. It NEVER falls back to a
    hardcoded constant, an unset secret is a hard error, because a public
    default would let anyone forge admin tokens.
    """
    secret = os.getenv("JWT_SECRET") or getattr(settings, "JWT_SECRET", None)
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not configured. Set it in the environment / .env "
            "before starting the API."
        )
    return secret


def jwt_algorithm() -> str:
    return os.getenv("JWT_ALGORITHM") or settings.JWT_ALGORITHM or "HS256"


# Fallback defaults only, used when the corresponding env var isn't set,
# so a fresh checkout still works with zero config. Any real deployment
# should set PROD_ALLOWED_ORIGINS (and DEV_ALLOWED_ORIGINS / ALLOWED_ORIGINS
# as needed) rather than relying on these being edited in source.
_DEFAULT_PROD_FRONTEND_ORIGINS = [
    "https://predicti-x-frontend.vercel.app",
    "https://predicti-x-frontend-dinusha-ekanayakes-projects.vercel.app",
]
_DEFAULT_DEV_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.56.1:3000",
    "http://192.168.56.1:3001",
]


def _origins_from_env(var_name: str, default: list[str]) -> list[str]:
    raw = os.getenv(var_name, "")
    parsed = [o.strip() for o in raw.split(",") if o.strip()]
    return parsed or default


def allowed_frontend_origins() -> list[str]:
    """The frontend origins this API trusts, single source of truth.

    Used for both the CORS allowlist (main.py) and the server-side PDF
    renderer's network allowlist (asset_reports.py), so the two never drift
    apart.

    Fully configurable via environment, with the current known deployments
    as safe fallback defaults (not secrets, these are public URLs, so a
    hardcoded default is fine; the point is that changing them, e.g. adding
    a new Vercel alias or a staging domain, should never require a code
    change and redeploy):
      - PROD_ALLOWED_ORIGINS: comma-separated, replaces the prod default list.
      - DEV_ALLOWED_ORIGINS: comma-separated, replaces the dev default list.
      - ALLOWED_ORIGINS: comma-separated, always appended on top of the above.
      - ENV=production excludes dev origins entirely.
    """
    is_production = os.getenv("ENV", "").strip().lower() == "production"
    prod_origins = _origins_from_env("PROD_ALLOWED_ORIGINS", _DEFAULT_PROD_FRONTEND_ORIGINS)
    extra = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    origins = list(set(prod_origins + extra))
    if not is_production:
        dev_origins = _origins_from_env("DEV_ALLOWED_ORIGINS", _DEFAULT_DEV_FRONTEND_ORIGINS)
        origins = list(set(origins + dev_origins))
    return origins
