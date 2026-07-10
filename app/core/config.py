import os

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()


def jwt_secret() -> str:
    """Return the JWT signing secret, failing fast if it is not configured.

    Reads the live environment first (so a value injected at deploy time on
    EC2/Vercel is honoured even if it differs from the .env baked at import),
    then falls back to the validated Settings value. It NEVER falls back to a
    hardcoded constant — an unset secret is a hard error, because a public
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
