from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

DATABASE_URL = os.getenv("DATABASE_URL")

print(os.getenv("DATABASE_URL"))  # Debugging line to check if DATABASE_URL is loaded correctly
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
