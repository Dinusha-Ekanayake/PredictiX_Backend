"""
app/core/storage.py
Handles PDF uploads to Supabase Storage.
Reads credentials directly from environment — no dependency on Settings object.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv(override=True)


class SupabaseStorage:
    def __init__(self):
        self.url    = os.getenv("SUPABASE_URL")
        self.key    = os.getenv("SUPABASE_KEY")
        self.client: Client | None = None

        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                print(f"[storage] WARNING: Failed to initialize Supabase client: {e}")

    def _ensure_bucket_exists(self, bucket: str):
        if not self.client:
            return
        try:
            buckets = self.client.storage.list_buckets()
            if any(b.name == bucket for b in buckets):
                return
            print(f"[storage] Bucket '{bucket}' not found. Creating...")
            self.client.storage.create_bucket(bucket, options={"public": True})
            print(f"[storage] Bucket '{bucket}' created.")
        except Exception as e:
            print(f"[storage] WARNING: Could not verify/create bucket '{bucket}': {e}")

    def upload_file(self, bucket: str, file_path: str, destination_path: str) -> str:
        if not self.client:
            print(f"[storage] Mocking upload — client not initialized")
            return f"https://mock.supabase.co/storage/v1/object/public/{bucket}/{destination_path}"

        self._ensure_bucket_exists(bucket)

        try:
            with open(file_path, "rb") as f:
                self.client.storage.from_(bucket).upload(
                    path=destination_path,
                    file=f,
                    file_options={"content-type": "application/pdf"},
                )
            return self.client.storage.from_(bucket).get_public_url(destination_path)

        except Exception as e:
            if "already exists" in str(e).lower():
                return self.client.storage.from_(bucket).get_public_url(destination_path)
            print(f"[storage] Upload error: {e}")
            raise e


supabase_storage = SupabaseStorage()