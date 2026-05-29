from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the PredictiX_backend package directory (works regardless of cwd)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

SUPABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
PROJECT_REF = os.getenv("PROJECT_REF")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://postgres:{SUPABASE_PASSWORD}@db.{PROJECT_REF}.supabase.co:5432/postgres"
)

engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()