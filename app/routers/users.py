from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import date
import httpx

from app.db.session import get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter(tags=["Users"])


def create_supabase_auth_user(email: str, password: str) -> UUID:
    """Creates user in Supabase Auth and returns the new UUID."""
    url = f"{settings.supabase_url}/auth/v1/admin/users"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,   # skip confirmation email
    }

    response = httpx.post(url, json=payload, headers=headers)

    if response.status_code not in (200, 201):
        raise HTTPException(
            status_code=400,
            detail=f"Supabase Auth error: {response.text}"
        )

    return UUID(response.json()["id"])


@router.get("", response_model=List[UserOut], summary="List all users")
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/{user_id}", response_model=UserOut, summary="Get user by ID")
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=UserOut, status_code=201, summary="Create user")
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    # Check duplicate email in AddUser
    if payload.email:
        if db.query(User).filter(User.email == payload.email).first():
            raise HTTPException(status_code=409, detail="Email already registered")

    # Step 1: Create in Supabase Auth → get UUID
    auth_uuid = create_supabase_auth_user(
        email=payload.email,
        password=payload.password or settings.default_password,
    )

    # Step 2: Insert into AddUser with the same UUID
    user = User(
        user_id           = auth_uuid,       # must match profiles.id
        first_name        = payload.first_name,
        last_name         = payload.last_name,
        email             = payload.email,
        role              = payload.role.upper() if payload.role else "USER",
        status            = payload.status or "active",
        department        = payload.department,
        residence_address = payload.residence_address,
        contact_no        = payload.contact_no,
        warehouse         = payload.warehouse,
        created_at        = date.today(),
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut, summary="Update user")
def update_user(user_id: UUID, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", summary="Delete user")
def delete_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return {"success": True, "message": "User deleted"}