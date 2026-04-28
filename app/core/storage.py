import os
import uuid
from supabase import create_client, Client
from app.core.config import settings

class SupabaseStorage:
    @staticmethod
    def upload_file(bucket: str, file_path: str, destination_path: str) -> str:
        with open(file_path, "rb") as f:
            supabase.storage.from_(bucket).upload(destination_path, f, file_options={"content-type": "application/pdf"})
        
        return supabase.storage.from_(bucket).get_public_url(destination_path)

supabase_storage = SupabaseStorage()

class SupabaseStorageClient:
    def __init__(self):
        self.url = settings.SUPABASE_URL
        self.key = settings.SUPABASE_KEY
        self.bucket_name = "reports"
        
        # Initialize supabase client if configured
        self.client = None
        if self.url and self.key:
            try:
                from supabase import create_client, Client
                self.client: Client = create_client(self.url, self.key)
            except ImportError:
                print("Supabase Python client not installed. Upload will be mocked.")

    def upload_file(self, file_path: str, destination_path: str) -> str:
        """
        Uploads a file to Supabase Storage and returns the public URL.
        """
        if not self.client:
            # Mock behavior if not configured or missing dependency
            print(f"Mocking upload to {self.bucket_name}/{destination_path}")
            return f"https://mock.supabase.co/storage/v1/object/public/{self.bucket_name}/{destination_path}"
            
        try:
            with open(file_path, "rb") as f:
                res = self.client.storage.from_(self.bucket_name).upload(
                    path=destination_path,
                    file=f,
                    file_options={"content-type": "application/pdf"}
                )
            
            # Get public URL
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(destination_path)
            return public_url
        except Exception as e:
            # E.g. bucket doesn't exist, invalid permissions
            print(f"Error uploading to Supabase: {e}")
            raise e
