from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
PROJECT_REF = os.getenv("PROJECT_REF")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://postgres:{SUPABASE_PASSWORD}@db.{PROJECT_REF}.supabase.co:5432/postgres"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()