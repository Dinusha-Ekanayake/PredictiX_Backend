from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.engine import URL
import os
from dotenv import load_dotenv
from sqlalchemy.engine import URL


load_dotenv(override=True)

PROJECT_REF = os.getenv("PROJECT_REF", "ulpjoljukculqqrwlwup")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Build URL object — handles special characters in password automatically, no encoding needed
url_object = URL.create(
    drivername="postgresql+psycopg2",
    username="postgres",
    password=DATABASE_PASSWORD,
    host="aws-0-ap-southeast-1.pooler.supabase.com",
    port=5432,
    database="postgres",
    query={"sslmode": "require", "project": PROJECT_REF},
)

engine = create_engine(
    url_object,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()