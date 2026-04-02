from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.deps import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate 

router = APIRouter(prefix="/users", tags=["Users"])


# TEMP ROLE SYSTEM (same as assets)
def require_admin(role: str = "USER"):
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")

def get_role(role: str = Query("USER")):
    return role


# GET ALL USERS
@router.get("", response_model=list[UserOut], summary="List all users")
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


# GET USER BY ID
@router.get("/{user_id}", response_model=UserOut, summary="Get user by ID")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# CREATE USER
@router.post("", response_model=UserOut, summary="Create user")
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),
):
    require_admin(role)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        email=payload.email,
        password=payload.password,
        role=payload.role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


# UPDATE USER
@router.put("/{user_id}", response_model=UserOut, summary="Update user")
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),
):
    require_admin(role)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)

    for key, value in data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)

    return user


# DELETE USER
@router.delete("/{user_id}", summary="Delete user")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    role: str = Depends(get_role),
):
    require_admin(role)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()

    return {"success": True, "message": "User deleted"}