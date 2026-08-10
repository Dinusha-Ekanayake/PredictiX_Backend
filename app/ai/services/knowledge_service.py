import os
import requests
from app.db.supabase_client import supabase

def search_knowledge(query: str, match_count: int = 3) -> list:
    try:
        # Use Hugging Face Inference API instead of heavy local torch/transformers models
        api_url = os.getenv("HF_INFERENCE_API_URL")
        if not api_url:
            print("HF API Error: HF_INFERENCE_API_URL is not configured in the environment")
            return []
            
        headers = {}
        if token := os.getenv("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
            
        # wait_for_model can legitimately take a while on a cold HF endpoint,
        # but with no timeout at all a hanging endpoint blocked the calling
        # request (chat/report generation) indefinitely instead of failing
        # over to the empty-results path below.
        response = requests.post(
            api_url, headers=headers,
            json={"inputs": [query], "options": {"wait_for_model": True}},
            timeout=60,
        )
        if response.status_code != 200:
            print(f"HF API Error: {response.text}")
            return []
            
        # The feature-extraction pipeline for sentence-transformers returns a 1D array per input
        embedding = response.json()[0]
        
        response = supabase.rpc("match_knowledge", {
            "query_embedding": embedding,
            "match_count": match_count
        }).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Knowledge search error: {e}")
        return []
