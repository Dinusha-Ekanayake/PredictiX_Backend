"""
PredictiX KB Vector Store
===========================
pgvector based vector store using SentenceTransformers.
Loads KBDocuments from PostgreSQL database using cosine similarity.
"""

from __future__ import annotations

import os
from sentence_transformers import SentenceTransformer
from app.db.session import SessionLocal
from app.models import KBDocument
from sqlalchemy import select

class KBVectorStore:
    def __init__(self) -> None:
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def retrieve(self, query: str, top_k: int = 4, min_score: float = 0.05) -> list[dict]:
        """
        Retrieve top_k most relevant KB chunks for a query string using pgvector cosine distance.
        """
        q_vec = self.model.encode(query).tolist()
        
        with SessionLocal() as db:
            # pgvector cosine_distance returns (1 - cosine_similarity), 
            # so we order by distance ascending.
            # To get similarity, we do 1 - distance.
            stmt = select(KBDocument, KBDocument.embedding.cosine_distance(q_vec).label("distance")) \
                   .order_by("distance") \
                   .limit(top_k)
            
            results = db.execute(stmt).all()
            
            out = []
            for doc, dist in results:
                similarity = 1.0 - float(dist)
                if similarity >= min_score:
                    out.append({
                        "id": doc.id,
                        "text": doc.text,
                        "tags": doc.tags,
                        "section": doc.id,
                        "score": similarity
                    })
            return out

    def retrieve_by_tags(self, tags: list[str], top_k: int = 6) -> list[dict]:
        """
        Retrieve documents matching any of the provided tags (exact match).
        """
        with SessionLocal() as db:
            docs = db.query(KBDocument).all()
            results = []
            for doc in docs:
                doc_tags = set(doc.tags or [])
                overlap = doc_tags.intersection(set(tags))
                if overlap:
                    results.append({
                        "id": doc.id, 
                        "text": doc.text, 
                        "tags": doc.tags, 
                        "section": doc.id, 
                        "tag_matches": len(overlap)
                    })
            results.sort(key=lambda x: -x["tag_matches"])
            return results[:top_k]

    def get_all_text_for_section(self, query: str) -> str:
        chunks = self.retrieve(query, top_k=4)
        if not chunks:
            return ""
        return "\n\n".join(
            f"[KB: {c.get('section', c['id'])}]\n{c['text']}"
            for c in chunks
        )

    def build_full_kb_context(self) -> str:
        lines = [
            "=" * 64,
            "PREDICTIX KNOWLEDGE BASE — MAINTENANCE STANDARDS & SOURCES",
            "Layers: Statutory (law) — OEM schedules — ISO 55000/55001 — SMRP — FMEA — Climate",
            "=" * 64,
        ]
        with SessionLocal() as db:
            docs = db.query(KBDocument).all()
            for doc in docs:
                lines.append(f"\n[{doc.id}]")
                lines.append(doc.text)
        return "\n".join(lines)


_store: KBVectorStore | None = None

def get_kb_store() -> KBVectorStore:
    global _store
    if _store is None:
        _store = KBVectorStore()
    return _store
