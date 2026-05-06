import os
import uuid
from supabase import create_client, Client
from app.core.config import settings

class SupabaseStorage:
    def __init__(self):
        self.url = settings.SUPABASE_URL
        self.key = settings.SUPABASE_KEY
        self.client = None
        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                print(f"Failed to initialize Supabase client: {e}")

    def _ensure_bucket_exists(self, bucket: str):
        """Try to create the bucket if it doesn't exist. Might fail if not using service_role key."""
        if not self.client:
            return
        try:
            # Check if bucket exists
            buckets = self.client.storage.list_buckets()
            if any(b.name == bucket for b in buckets):
                return
            
            # Create bucket if missing
            print(f"Bucket '{bucket}' not found. Attempting to create...")
            self.client.storage.create_bucket(bucket, options={"public": True})
            print(f"Bucket '{bucket}' created successfully.")
        except Exception as e:
            print(f"Note: Could not verify/create bucket '{bucket}': {e}")
            # We don't raise here, as upload might still work if it exists but list_buckets failed

    def upload_file(self, bucket: str, file_path: str, destination_path: str) -> str:
        if not self.client:
            print(f"Mocking upload to {bucket}/{destination_path} (Client not initialized)")
            return f"https://mock.supabase.co/storage/v1/object/public/{bucket}/{destination_path}"

        # Ensure bucket exists
        self._ensure_bucket_exists(bucket)

        try:
            with open(file_path, "rb") as f:
                self.client.storage.from_(bucket).upload(
                    path=destination_path,
                    file=f,
                    file_options={"content-type": "application/pdf"}
                )
            
            return self.client.storage.from_(bucket).get_public_url(destination_path)
        except Exception as e:
            # If upload fails, check if it's because it already exists
            error_str = str(e)
            if "already exists" in error_str.lower():
                return self.client.storage.from_(bucket).get_public_url(destination_path)
            
            print(f"Supabase Upload Error: {e}")
            raise e

supabase_storage = SupabaseStorage()
