from sentence_transformers import SentenceTransformer
from app.db.supabase_client import supabase

model = SentenceTransformer('all-MiniLM-L6-v2')

def search_knowledge(query: str, match_count: int = 3) -> list:
    # Convert question to embedding locally
    embedding = model.encode(query).tolist()

    # Search Supabase KB
    response = supabase.rpc("match_knowledge", {
        "query_embedding": embedding,
        "match_count": match_count
    }).execute()

    return response.data