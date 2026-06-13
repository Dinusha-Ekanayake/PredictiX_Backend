import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

bucket_name = "ticket-attachments"

# Check if bucket exists
try:
    buckets = supabase.storage.list_buckets()
    bucket_names = [b.name for b in buckets]
    if bucket_name in bucket_names:
        print(f"Bucket '{bucket_name}' already exists.")
    else:
        # Create bucket and make it public
        res = supabase.storage.create_bucket(bucket_name, options={"public": True})
        print(f"Bucket '{bucket_name}' created successfully: {res}")
except Exception as e:
    print(f"An error occurred: {e}")
