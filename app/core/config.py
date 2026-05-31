from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str           # kept but no longer used for connection
    JWT_SECRET: str
    DATABASE_PASSWORD: str      # ← this is used instead
    
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str
    project_ref: str
    default_password: str
    database_key: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()