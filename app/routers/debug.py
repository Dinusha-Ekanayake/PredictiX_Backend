from fastapi import APIRouter, Depends
import os

router = APIRouter(prefix="/debug", tags=["Debug"])

@router.get("/supabase-key")
def get_supabase_key_info():
    """Return a masked version of the Supabase service‑role key and URL for debugging.
    This endpoint is only for local development; do NOT expose in production.
    """
    url = os.getenv("SUPABASE_URL", "<missing>")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY") or "<missing>"
    masked = key[:8] + "..." if key != "<missing>" else "<missing>"
    return {"supabase_url": url, "key_preview": masked}
