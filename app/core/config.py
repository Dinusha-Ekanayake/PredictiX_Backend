from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str

    # Supabase & DB keys
    supabase_url: str
    supabase_key: str
    supabase_service_role_key: str
    project_ref: str
    default_password: str
    database_key: str
    database_password: str

    class Config:
        env_file = ".env"
        extra = "ignore"  # ignores unknown keys
        
settings = Settings()