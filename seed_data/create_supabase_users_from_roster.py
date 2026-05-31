
import os
import pandas as pd
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ROSTER_CSV = os.environ.get("ROSTER_CSV", "predictix_user_roster_lankalogix_colombo.csv")
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "TempPass#2026")


supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
roster = pd.read_csv(r"E:\BSc.(Hons) in Artificial Intelligence\Semesters\Year 02\Software Project\predictix_backend\PredictiX_backend\app\seed_data_to_db_v1\predictix_user_roster_lankalogix_colombo.csv")

for _, row in roster.iterrows():
    email = row["email"]
    full_name = row["full_name"]
    try:
        supabase.auth.admin.create_user({
            "email": email,
            "password": DEFAULT_PASSWORD,
            "email_confirm": True,
            "user_metadata": {
                "full_name": full_name
            }
        })
        print(f"CREATED: {email}")
    except Exception as e:
        print(f"SKIPPED/ERROR: {email} -> {e}")

print("Done. After creating users, run the SQL seed file.")


