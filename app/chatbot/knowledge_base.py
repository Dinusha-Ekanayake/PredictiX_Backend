"""Knowledge Base CRUD router — manages articles that feed the chatbot's RAG pipeline.

Articles are stored in the Supabase `knowledge_base` table. On create/update the
title+content is embedded via the HuggingFace Inference API (same model used by
search_knowledge) and the resulting vector is stored alongside the text so the
existing `match_knowledge` RPC can perform cosine-similarity retrieval.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_current_user, is_admin_role, get_db
from app.db.supabase_client import supabase
from app.chatbot.knowledge_service import embed_text

log = logging.getLogger("predictix.knowledge_base")

router = APIRouter(prefix="/knowledge-base", tags=["Knowledge Base"])

# ─── Predefined categories ────────────────────────────────────────────────────
KB_CATEGORIES = [
    "Maintenance",
    "Safety",
    "Operations",
    "Troubleshooting",
    "Policies",
    "Training",
    "General",
]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class KBArticleCreate(BaseModel):
    title: str
    content: str
    category: Optional[str] = "General"
    source: Optional[str] = ""
    tags: Optional[list[str]] = None


class KBArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[list[str]] = None
    is_active: Optional[bool] = None


class KBArticleOut(BaseModel):
    id: str
    title: str
    content: str
    category: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[list] = None
    is_active: bool
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[str])
def list_categories():
    """Return the predefined category list for dropdowns."""
    return KB_CATEGORIES


@router.get("/", response_model=list[KBArticleOut])
def list_articles(
    category: Optional[str] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    current_user: object = Depends(get_current_user),
):
    """List all knowledge base articles. Admins only."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can view the knowledge base")

    q = supabase.from_("knowledge_base").select(
        "id,title,content,category,source,tags,is_active,created_by,created_at,updated_at"
    )
    if not include_inactive:
        q = q.eq("is_active", True)
    if category:
        q = q.eq("category", category)
    if search:
        q = q.or_(f"title.ilike.%{search}%,content.ilike.%{search}%")

    response = q.order("created_at", desc=True).execute()
    return response.data or []


@router.get("/{article_id}", response_model=KBArticleOut)
def get_article(
    article_id: str,
    current_user: object = Depends(get_current_user),
):
    """Get a single article by ID."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can view KB articles")

    response = supabase.from_("knowledge_base").select(
        "id,title,content,category,source,tags,is_active,created_by,created_at,updated_at"
    ).eq("id", article_id).single().execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Article not found")
    return response.data


@router.post("/", response_model=KBArticleOut)
def create_article(
    payload: KBArticleCreate,
    current_user: object = Depends(get_current_user),
):
    """Create a new KB article and auto-embed it for semantic search."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can create KB articles")

    title = payload.title.strip()
    content = payload.content.strip()

    if not title or not content:
        raise HTTPException(status_code=422, detail="Title and content are required")

    # Generate embedding for semantic search
    embedding = None
    try:
        embedding = embed_text(f"{title}. {content}")
    except Exception as e:
        log.warning("Failed to generate embedding for KB article: %s", e)

    insert_data = {
        "title": title,
        "content": content,
        "category": payload.category or "General",
        "source": payload.source or "",
        "tags": payload.tags or [],
        "is_active": True,
        "created_by": str(getattr(current_user, "id", "")),
    }
    if embedding:
        insert_data["embedding"] = embedding

    response = supabase.from_("knowledge_base").insert(insert_data).select(
        "id,title,content,category,source,tags,is_active,created_by,created_at,updated_at"
    ).single().execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create article")
    return response.data


@router.put("/{article_id}", response_model=KBArticleOut)
def update_article(
    article_id: str,
    payload: KBArticleUpdate,
    current_user: object = Depends(get_current_user),
):
    """Update an existing KB article. Re-embeds if title or content changed."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can update KB articles")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    updates["updated_at"] = datetime.utcnow().isoformat()

    # Re-embed if text content changed
    if "title" in updates or "content" in updates:
        # Fetch current to merge
        current = supabase.from_("knowledge_base").select("title,content").eq("id", article_id).single().execute()
        if current.data:
            new_title = updates.get("title", current.data["title"])
            new_content = updates.get("content", current.data["content"])
            try:
                updates["embedding"] = embed_text(f"{new_title}. {new_content}")
            except Exception as e:
                log.warning("Failed to re-embed KB article: %s", e)

    response = supabase.from_("knowledge_base").update(updates).eq("id", article_id).select(
        "id,title,content,category,source,tags,is_active,created_by,created_at,updated_at"
    ).single().execute()

    if not response.data:
        raise HTTPException(status_code=404, detail="Article not found")
    return response.data


@router.post("/{article_id}/toggle", response_model=KBArticleOut)
def toggle_article(
    article_id: str,
    current_user: object = Depends(get_current_user),
):
    """Toggle an article's active/inactive status."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can toggle KB articles")

    current = supabase.from_("knowledge_base").select("is_active").eq("id", article_id).single().execute()
    if not current.data:
        raise HTTPException(status_code=404, detail="Article not found")

    new_status = not current.data["is_active"]
    response = supabase.from_("knowledge_base").update({
        "is_active": new_status,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", article_id).select(
        "id,title,content,category,source,tags,is_active,created_by,created_at,updated_at"
    ).single().execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to toggle article")
    return response.data


@router.delete("/{article_id}")
def delete_article(
    article_id: str,
    current_user: object = Depends(get_current_user),
):
    """Permanently delete a KB article."""
    if not is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Only admins can delete KB articles")

    supabase.from_("knowledge_base").delete().eq("id", article_id).execute()
    return {"message": "Article deleted"}
