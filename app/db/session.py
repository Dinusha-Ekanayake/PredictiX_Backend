from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Build URL safely — avoids @ in password breaking URL parsing
connection_url = URL.create(
    drivername="postgresql+psycopg2",
    username="postgres.ulpjoljukculqqrwlwup",
    password=settings.DATABASE_PASSWORD,      # raw password, no encoding needed
    host="aws-1-ap-southeast-2.pooler.supabase.com",
    port=5432,
    database="postgres",
    query={"sslmode": "require"},
)

engine = create_engine(
    connection_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()