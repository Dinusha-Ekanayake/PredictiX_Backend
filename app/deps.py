from .db import SessionLocal
import os

def get_db():
    """
    Database session dependency.
    If DATABASE_PASSWORD is not configured, yields None to avoid connection timeout.
    Otherwise attempts to create a live session.
    """
    # Check if database credentials are configured before attempting connection
    if not os.getenv("DATABASE_PASSWORD"):
        print("[INFO] DATABASE_PASSWORD not configured - returning None")
        yield None
        return
    
    try:
        db = SessionLocal()
        yield db
    except Exception as e:
        print(f"Database connection failed: {str(e)}")
        yield None
    finally:
        try:
            db.close()
        except:
            pass

# dinusha
