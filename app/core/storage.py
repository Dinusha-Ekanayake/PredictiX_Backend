"""
app/core/storage.py
Handles PDF uploads to Supabase Storage.
Reads credentials directly from environment variables.
"""

import logging
import os
from dotenv import load_dotenv
from supabase import create_client, Client

log = logging.getLogger(__name__)

load_dotenv(override=True)


class SupabaseStorage:
    def __init__(self):
        self.url    = os.getenv("SUPABASE_URL")
        from app.db.supabase_client import supabase_key

        self.key = supabase_key()
        self.client: Client | None = None

        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                log.warning(f"Failed to initialize Supabase client: {e}")

    def _ensure_bucket_exists(self, bucket: str):
        if not self.client:
            return
        try:
            buckets = self.client.storage.list_buckets()
            if any(b.name == bucket for b in buckets):
                return
            log.warning(f"Bucket '{bucket}' not found. Attempting to create...")
            self.client.storage.create_bucket(bucket, options={"public": True})
            log.info(f"Bucket '{bucket}' created successfully.")
        except Exception as e:
            log.warning(f"Note: Could not verify/create bucket '{bucket}': {e}")

    def upload_file(self, bucket: str, file_path: str, destination_path: str) -> str:
        if not self.client:
            # Never pretend: a made-up URL here was recorded as if the file existed.
            raise RuntimeError("File storage is not configured (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY).")

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
            log.warning(f"Supabase Upload Error: {e}")
            raise e


supabase_storage = SupabaseStorage()

