"""
PredictiX KB Vector Store
===========================
TF-IDF based vector store using sklearn (already in .venv — zero new installs).
Loads KB_DOCUMENTS dynamically from the Supabase Postgres database.

Features lazy loading so it doesn't run blocking network requests during module import
or FastAPI app startup.
"""

from __future__ import annotations

import logging
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.db.supabase_client import supabase

log = logging.getLogger("predictix.kb_vector_store")


class KBVectorStore:
    """
    Lightweight in-memory vector store using TF-IDF + cosine similarity.
    Loads articles dynamically from the Supabase database.
    """

    def __init__(self) -> None:
        self._docs = None
        self._ids = []
        self._texts = []
        self._tags = []
        self._vectorizer = None
        self._matrix = None

    def _ensure_loaded(self) -> None:
        """Lazy load documents and fit the TF-IDF index if not loaded yet."""
        if self._docs is not None:
            return

        try:
            log.info("Lazy-loading knowledge base documents from Supabase...")
            # Query active articles from database
            response = supabase.from_("knowledge_base").select("id, title, content, category, tags, source").eq("is_active", True).execute()
            docs = []
            for r in (response.data or []):
                docs.append({
                    "id": r["id"],
                    "section": f"{r.get('category') or 'General'}: {r['title']}",
                    "text": r["content"],
                    "tags": r.get("tags") or [],
                    "source": r.get("source") or ""
                })
            
            self._docs = docs
            log.info("Loaded %d active articles from database.", len(docs))
        except Exception as e:
            log.error("Failed to load knowledge base articles from database: %s", e)
            self._docs = []

        self._ids   = [d["id"]   for d in self._docs]
        self._texts = [d["text"] for d in self._docs]
        self._tags  = [d.get("tags", []) for d in self._docs]

        # Fit TF-IDF matrix if we have documents
        if self._texts:
            self._vectorizer = TfidfVectorizer(
                strip_accents="unicode",
                lowercase=True,
                stop_words="english",
                ngram_range=(1, 2),
                max_features=2000,
                sublinear_tf=True,
            )
            self._matrix = self._vectorizer.fit_transform(self._texts)
        else:
            self._vectorizer = None
            self._matrix = None

    # ── Public API ───────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 4, min_score: float = 0.05) -> list[dict]:
        """
        Retrieve top_k most relevant KB chunks for a query string.
        Returns list of dicts with: id, section, text, score.
        """
        self._ensure_loaded()
        if not self._matrix or not self._vectorizer:
            return []

        q_vec  = self._vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self._matrix)[0]
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            {
                **self._docs[i],
                "score": float(scores[i]),
            }
              for i in top_idx
              if scores[i] >= min_score
        ]

    def retrieve_by_tags(self, tags: list[str], top_k: int = 6) -> list[dict]:
        """
        Retrieve documents matching any of the provided tags (exact match).
        Useful for deterministic section-scoped retrieval.
        """
        self._ensure_loaded()
        results = []
        for doc in self._docs:
            doc_tags = set(doc.get("tags", []))
            overlap = doc_tags.intersection(set(tags))
            if overlap:
                results.append({**doc, "tag_matches": len(overlap)})
        results.sort(key=lambda x: -x["tag_matches"])
        return results[:top_k]

    def get_all_text_for_section(self, query: str) -> str:
        """
        Return concatenated text of top-4 KB chunks for a given query.
        Used to inject into LLM system prompt.
        """
        chunks = self.retrieve(query, top_k=4)
        if not chunks:
            return ""
        return "\n\n".join(
            f"[KB: {c['section']}]\n{c['text']}"
            for c in chunks
        )

    def build_full_kb_context(self) -> str:
        """
        Return ALL KB documents as a structured, source-grouped string for
        full-context LLM injection. Preferred for the complete warehouse report.
        """
        self._ensure_loaded()
        lines = [
            "=" * 64,
            "PREDICTIX KNOWLEDGE BASE — MAINTENANCE STANDARDS & SOURCES",
            "Layers: Statutory (law) · OEM schedules · ISO 55000/55001 · SMRP · FMEA · Climate",
            "=" * 64,
        ]
        for doc in self._docs:
            src = doc.get("source")
            lines.append(f"\n[{doc['section']}]")
            if src:
                lines.append(f"(Source: {src})")
            lines.append(doc["text"])
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────
_store: KBVectorStore | None = None


def get_kb_store() -> KBVectorStore:
    """Return singleton KB vector store (lazy-initialised)."""
    global _store
    if _store is None:
        _store = KBVectorStore()
    return _store
