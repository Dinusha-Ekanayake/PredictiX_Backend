from app.db.supabase_client import supabase


def get_vehicle_by_id(vehicle_id: str):
    response = (
        supabase.table("vehicles")
        .select("*")
        .eq("id", vehicle_id)
        .single()
        .execute()
    )
    return response.data


def get_latest_snapshot(vehicle_id: str):
    response = (
        supabase.table("vehicle_snapshots")
        .select("*")
        .eq("vehicle_id", vehicle_id)
        .order("snapshot_date", desc=True)
        .limit(1)
        .single()
        .execute()
    )
    return response.data


def save_prediction(prediction_data: dict):
    response = supabase.table("predictions").insert(prediction_data).execute()
    return response.data