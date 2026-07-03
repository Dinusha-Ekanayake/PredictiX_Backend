from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.deps import get_current_user, is_admin_role
from app.db.supabase_client import supabase

router = APIRouter(prefix="/faqs", tags=["FAQs"])


class FaqCreate(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None


class FaqUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class FaqOut(BaseModel):
    id: str
    question: str
    answer: str
    category: Optional[str] = None
    tags: Optional[list] = None
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("/", response_model=list[FaqOut])
def list_faqs():
    response = supabase.from_("faqs").select(
        "id,question,answer,category,tags,is_active,created_at,updated_at"
    ).eq("is_active", True).order("created_at", desc=True).execute()
    return response.data or []


@router.post("/", response_model=FaqOut)
def create_faq(payload: FaqCreate, current_user: object = Depends(get_current_user)):
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can add FAQs")

    response = supabase.from_("faqs").insert({
        "question": payload.question.strip(),
        "answer": payload.answer.strip(),
        "category": payload.category,
        "is_active": True,
    }).select("id,question,answer,category,tags,is_active,created_at,updated_at").single().execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to insert FAQ")
    return response.data


@router.put("/{faq_id}", response_model=FaqOut)
def update_faq(faq_id: str, payload: FaqUpdate, current_user: object = Depends(get_current_user)):
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can update FAQs")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    updates["updated_at"] = datetime.utcnow().isoformat()

    response = supabase.from_("faqs").update(updates).eq("id", faq_id).select(
        "id,question,answer,category,tags,is_active,created_at,updated_at"
    ).single().execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return response.data


@router.delete("/{faq_id}")
def delete_faq(faq_id: str, current_user: object = Depends(get_current_user)):
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can delete FAQs")

    supabase.from_("faqs").delete().eq("id", faq_id).execute()
    return {"message": "FAQ deleted"}
