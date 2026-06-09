from functools import lru_cache
from app.db.supabase_client import supabase


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer('all-MiniLM-L6-v2')


def search_knowledge(query: str, match_count: int = 3) -> list:
    try:
        embedding = _get_model().encode(query).tolist()
        response = supabase.rpc("match_knowledge", {
            "query_embedding": embedding,
            "match_count": match_count
        }).execute()
        
        if not response.data:
            return []
            
        # Filter out low-similarity results to prevent irrelevant RAG sources.
        # A threshold of 0.35 is chosen for the all-MiniLM-L6-v2 model to ensure relevance.
        filtered_results = [
            r for r in response.data 
            if float(r.get("similarity") or 0) >= 0.35
        ]
        return filtered_results
    except Exception as e:
        print(f"Knowledge search error: {e}")
        return []
