from sentence_transformers import SentenceTransformer

# Import supabase client - check which path works
try:
    from app.db.supabase_client import supabase
except ImportError:
    try:
        from app.db.session import supabase
    except ImportError:
        from app.db import supabase

# Load embedding model locally
model = SentenceTransformer('all-MiniLM-L6-v2')

def search_knowledge(query: str, match_count: int = 3) -> list:
    try:
        embedding = model.encode(query).tolist()

        response = supabase.rpc("match_knowledge", {
            "query_embedding": embedding,
            "match_count": match_count
        }).execute()

        return response.data if response.data else []

    except Exception as e:
        print(f"Knowledge search error: {str(e)}")
        return []
