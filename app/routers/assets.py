"""
app/routers/assets.py
Rewritten to use Supabase REST client instead of SQLAlchemy.
"""

from fastapi import APIRouter, HTTPException, Query
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv(override=True)

router = APIRouter(prefix="/assets", tags=["Assets"])


def _get_supabase() -> Client:
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# ── List Assets ───────────────────────────────────────────────────
@router.get("/")
def list_assets(
    search: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    vehicle_type: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    health_band: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        supabase = _get_supabase()
        query = supabase.table("assets").select("*")

        if warehouse_id:
            query = query.eq("warehouse_id", warehouse_id)
        if department_id:
            query = query.eq("department_id", department_id)
        if status:
            query = query.eq("status", status)
        if vehicle_type:
            query = query.eq("vehicle_type", vehicle_type)
        if asset_type:
            query = query.eq("asset_type", asset_type)
        if health_band:
            query = query.eq("health_band", health_band)
        if search:
            query = query.or_(
                f"asset_name.ilike.%{search}%,"
                f"asset_code.ilike.%{search}%,"
                f"registration_number.ilike.%{search}%,"
                f"make.ilike.%{search}%,"
                f"model.ilike.%{search}%"
            )

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = query.execute()
        return result.data or []

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Count Assets ──────────────────────────────────────────────────
@router.get("/count")
def count_assets(
    warehouse_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    try:
        supabase = _get_supabase()
        query = supabase.table("assets").select("id", count="exact")

        if warehouse_id:
            query = query.eq("warehouse_id", warehouse_id)
        if status:
            query = query.eq("status", status)

        result = query.execute()
        return {"count": result.count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Get Single Asset ──────────────────────────────────────────────
@router.get("/{asset_id}")
def get_asset(asset_id: str):
    try:
        supabase = _get_supabase()
        result = supabase.table("assets").select("*").eq("id", asset_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return result.data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Create Asset ──────────────────────────────────────────────────
@router.post("/")
def create_asset(payload: dict):
    try:
        supabase = _get_supabase()

        # Check duplicate asset_code
        existing = supabase.table("assets").select("id").eq("asset_code", payload.get("asset_code", "")).execute()
        if existing.data:
            raise HTTPException(status_code=400, detail="Asset code already exists")

        result = supabase.table("assets").insert(payload).execute()
        return result.data[0] if result.data else {}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Update Asset ──────────────────────────────────────────────────
@router.put("/{asset_id}")
def update_asset(asset_id: str, payload: dict):
    try:
        supabase = _get_supabase()
        result = supabase.table("assets").update(payload).eq("id", asset_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Assign Asset ──────────────────────────────────────────────────
@router.patch("/{asset_id}/assign")
def assign_asset(asset_id: str, assigned_to: str | None = None):
    try:
        supabase = _get_supabase()
        result = supabase.table("assets").update({"assigned_to": assigned_to}).eq("id", asset_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Update Asset Status ───────────────────────────────────────────
@router.patch("/{asset_id}/status")
def update_asset_status(asset_id: str, status: str):
    try:
        supabase = _get_supabase()
        result = supabase.table("assets").update({"status": status}).eq("id", asset_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return result.data[0]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Delete Asset ──────────────────────────────────────────────────
@router.delete("/{asset_id}")
def delete_asset(asset_id: str):
    try:
        supabase = _get_supabase()
        result = supabase.table("assets").delete().eq("id", asset_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return {"message": "Asset deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))