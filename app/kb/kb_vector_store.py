"""
PredictiX KB Vector Store
===========================
Retrieval over the maintenance-standards corpus in the kb_documents table,
used by the warehouse report agent.

The query is embedded with the same all-MiniLM-L6-v2 model the stored vectors
were made with (app.chatbot.knowledge_service.embed_text: local model first,
hosted endpoint second), and ranked by cosine similarity in Postgres. When no
embedding can be made, the same kb_documents rows are ranked by TF-IDF
instead, so both paths search one corpus and only their scoring differs.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text

from app.chatbot.knowledge_service import embed_text, embedding_literal
from app.db.session import SessionLocal

log = logging.getLogger("predictix.kb_vector_store")


class KBVectorStore:
    """Semantic search over kb_documents, with a TF-IDF fallback on the same rows."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: list[dict] | None = None
        self._vectorizer = None
        self._matrix = None

    # ── corpus for the fallback and the tag/full-context helpers ──────────

    def _ensure_loaded(self) -> None:
        """Load kb_documents once and fit the TF-IDF index."""
        if self._docs is not None:
            return
        with self._lock:
            if self._docs is not None:
                return
            try:
                with SessionLocal() as db:
                    rows = db.execute(text("SELECT id, text, tags FROM kb_documents")).mappings().all()
                docs = [
                    {"id": r["id"], "section": r["id"], "text": r["text"], "tags": list(r["tags"] or [])}
                    for r in rows
                ]
                log.info("Loaded %d knowledge documents for keyword search.", len(docs))
            except Exception as e:
                log.error("Failed to load kb_documents: %s", e)
                docs = []

            if docs:
                self._vectorizer = TfidfVectorizer(
                    strip_accents="unicode",
                    lowercase=True,
                    stop_words="english",
                    ngram_range=(1, 2),
                    max_features=5000,
                    sublinear_tf=True,
                )
                self._matrix = self._vectorizer.fit_transform(d["text"] for d in docs)
            self._docs = docs

    def _lexical(self, query: str, top_k: int, min_score: float) -> list[dict]:
        self._ensure_loaded()
        if self._matrix is None or self._vectorizer is None:
            return []
        scores = cosine_similarity(self._vectorizer.transform([query]), self._matrix)[0]
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            {**self._docs[i], "score": float(scores[i]), "retrieval": "lexical"}
            for i in top_idx
            if scores[i] >= min_score
        ]

    # ── public API ────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 4, min_score: float = 0.25) -> list[dict]:
        """Top `top_k` documents for `query` scoring at least `min_score`."""
        try:
            vector = embed_text(query)
        except Exception as e:
            log.warning("Query embedding failed (%s); using keyword search over kb_documents.", e)
            return self._lexical(query, top_k, min_score=0.05)

        try:
            with SessionLocal() as db:
                rows = db.execute(text(
                    "SELECT id, text, tags, 1 - (embedding <=> CAST(:v AS vector)) AS score "
                    "FROM kb_documents WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"
                ), {"v": embedding_literal(vector), "k": int(top_k)}).mappings().all()
        except Exception as e:
            log.warning("pgvector retrieval failed (%s); using keyword search over kb_documents.", e)
            return self._lexical(query, top_k, min_score=0.05)

        return [
            {
                "id": r["id"],
                "section": r["id"],
                "text": r["text"],
                "tags": list(r["tags"] or []),
                "score": float(r["score"]),
                "retrieval": "semantic",
            }
            for r in rows
            if float(r["score"]) >= min_score
        ]

    def retrieve_by_tags(self, tags: list[str], top_k: int = 6) -> list[dict]:
        """Documents sharing the most tags with `tags` (exact match)."""
        self._ensure_loaded()
        wanted = set(tags)
        results = []
        for doc in self._docs or []:
            overlap = wanted.intersection(doc.get("tags", []))
            if overlap:
                results.append({**doc, "tag_matches": len(overlap)})
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
        """Every KB document as one source-grouped string, for full-context prompts."""
        self._ensure_loaded()
        lines = [
            "=" * 64,
            "PREDICTIX KNOWLEDGE BASE — MAINTENANCE STANDARDS & SOURCES",
            "Layers: Statutory (law) — OEM schedules — ISO 55000/55001 — SMRP — FMEA — Climate",
            "=" * 64,
        ]
        for doc in self._docs or []:
            lines.append(f"\n[{doc.get('section', doc['id'])}]")
            lines.append(doc["text"])
        return "\n".join(lines)


_store: KBVectorStore | None = None
_store_lock = threading.Lock()


def get_kb_store() -> KBVectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = KBVectorStore()
    return _store
