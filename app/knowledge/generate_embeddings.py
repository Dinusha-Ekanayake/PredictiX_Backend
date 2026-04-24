"""Standalone script to generate and store embeddings for KB rows with null embedding."""

from sentence_transformers import SentenceTransformer

from app.db.supabase_client import supabase


def generate_embeddings() -> None:
    """Generate embeddings for `knowledge_base` rows where embedding is null."""
    model = SentenceTransformer("all-MiniLM-L6-v2")

    response = supabase.table("knowledge_base").select("id, title, content").is_("embedding", "null").execute()
    rows = response.data or []

    if not rows:
        print("No rows found with null embedding.")
        return

    print(f"Found {len(rows)} rows to embed.")
    for row in rows:
        content = row.get("content") or ""
        embedding = model.encode(content).tolist()

        supabase.table("knowledge_base").update({"embedding": embedding}).eq("id", row["id"]).execute()
        print(f"Embedded row: {row.get('title', row['id'])}")

    print("Embedding generation complete.")


if __name__ == "__main__":
    generate_embeddings()