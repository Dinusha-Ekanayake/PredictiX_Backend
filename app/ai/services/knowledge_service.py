import os
import requests
from app.db.supabase_client import supabase

def _embedding_url() -> str:
    """Resolve the embedding endpoint."""
    configured = os.getenv("HF_INFERENCE_API_URL")
    if not configured:
        # Use default SentenceTransformers model router if not specified
        return "https://router.huggingface.co/hf-inference/models/sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction"
    return configured

def embed_text(text: str) -> list[float]:
    """Generate a 384-dim embedding vector for the given text.

    Uses the same HuggingFace Inference API endpoint as search_knowledge,
    so articles and queries are embedded in the same vector space.
    """
    api_url = _embedding_url()
    headers = {}
    if token := os.getenv("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    response = requests.post(
        api_url, headers=headers,
        json={"inputs": [text[:2000]], "options": {"wait_for_model": True}},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HF embedding API returned {response.status_code}: {response.text[:200]}")

    return response.json()[0]

def search_knowledge(query: str, match_count: int = 3) -> list:
    try:
        api_url = _embedding_url()
        headers = {}
        if token := os.getenv("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
            
        response = requests.post(
            api_url, headers=headers,
            json={"inputs": [query], "options": {"wait_for_model": True}},
            timeout=60,
        )
        if response.status_code != 200:
            print(f"HF API Error: {response.text}")
            return []
            
        embedding = response.json()[0]
        
        response = supabase.rpc("match_knowledge", {
            "query_embedding": embedding,
            "match_count": match_count
        }).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Knowledge search error: {e}")
        return []
