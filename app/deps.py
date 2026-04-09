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
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Decode JWT token and return the Profile of the logged-in user."""
    print(f"[DEBUG] get_current_user called with token: {token[:20] if token else 'NO TOKEN'}...")
    
    try:
        secret = os.getenv("JWT_SECRET", "supersecret")
        algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        print(f"[DEBUG] Decoding token with secret: {secret}, algorithm: {algorithm}")
        
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm]
        )
        print(f"[DEBUG] Token decoded successfully. Payload: {payload}")
        
        user_id: str = payload.get("sub")
        if not user_id:
            print("[DEBUG] No user_id in token payload")
            raise HTTPException(status_code=401, detail="Invalid token")
            
        print(f"[DEBUG] User ID from token: {user_id}")
    except JWTError as e:
        print(f"[DEBUG] JWTError during token decode: {e}")
        raise HTTPException(status_code=401, detail="Not authenticated")

    from app.models import Profile
    
    # Try to find user in database
    user = None
    if db:
        try:
            user = db.query(Profile).filter(Profile.id == user_id).first()
            if user:
                print(f"[DEBUG] User found in database: {user.email}")
            else:
                print(f"[DEBUG] User not found in database for ID: {user_id}")
        except Exception as e:
            print(f"[DEBUG] Error querying database: {e}")
            user = None
    else:
        print("[DEBUG] No database connection available")
    
    if not user:
        # For development: create a mock user object that works with endpoints
        # This has all the attributes needed by the profile endpoints
        email = payload.get("email", "test@example.com")
        role = payload.get("role", "user")
        
        print(f"[DEBUG] Creating MockProfile for email={email}, role={role}")
        
        # Try to find Transportation department (default) for the mock user
        # or use the user's email to find their real department
        dept_id = None
        try:
            from app.models import Department
            
            # First try to find based on email pattern or default to Transportation
            if "transportation" in email.lower():
                dept = db.query(Department).filter(Department.name == "Transportation").first()
            elif "electrical" in email.lower():
                dept = db.query(Department).filter(Department.name == "Electrical").first()
            elif "software" in email.lower():
                dept = db.query(Department).filter(Department.name == "Software").first()
            elif "mechanical" in email.lower():
                dept = db.query(Department).filter(Department.name == "Mechanical").first()
            else:
                # Default to Transportation (most users)
                dept = db.query(Department).filter(Department.name == "Transportation").first()
            
            if dept:
                dept_id = dept.id
                print(f"[DEBUG] Found department: {dept.name} ({dept_id})")
        except Exception as e:
            print(f"[DEBUG] Error fetching department: {e}")
        
        # Create a mock Profile class instance
        class MockProfile:
            def __init__(self, user_id, email, role, dept_id):
                self.id = user_id
                self.email = email
                self.role = role
                self.full_name = email.split("@")[0].replace(".", " ").title()
                self.phone = None
                self.status = "active"
                self.warehouse_id = None
                self.department_id = dept_id  # Set to actual department
                self.meta = {}
                self.employee_id = f"EMP-{user_id[:8]}"
        
        user = MockProfile(user_id, email, role, dept_id)
        print(f"[DEBUG] MockProfile created: id={user.id}, email={user.email}, role={user.role}, dept_id={user.department_id}")
        return user
    
    return user
