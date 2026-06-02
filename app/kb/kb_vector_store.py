"""
PredictiX KB Vector Store
===========================
TF-IDF based vector store using sklearn (already in .venv — zero new installs).
Loads KB_DOCUMENTS from kb_documents.py and enables semantic retrieval.

Why TF-IDF instead of dense embeddings:
- sklearn is already installed in the venv
- KB is small (~15 documents) — TF-IDF is accurate at this scale
- No model download, no GPU, instant startup
- The pgvector extension exists in Supabase DB (for future dense embedding upgrade)
"""

from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .kb_documents import KB_DOCUMENTS


class KBVectorStore:
    """
    Lightweight in-memory vector store using TF-IDF + cosine similarity.
    Built on existing sklearn installation — no new dependencies required.
    """

    def __init__(self) -> None:
        self._docs = KB_DOCUMENTS
        self._ids   = [d["id"]   for d in self._docs]
        self._texts = [d["text"] for d in self._docs]
        self._tags  = [d.get("tags", []) for d in self._docs]

        # Build TF-IDF matrix over all KB document texts
        self._vectorizer = TfidfVectorizer(
            strip_accents="unicode",
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2),          # unigrams + bigrams for better recall
            max_features=2000,
            sublinear_tf=True,           # log-normalization for length robustness
        )
        self._matrix = self._vectorizer.fit_transform(self._texts)

    # ── Public API ───────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 4, min_score: float = 0.05) -> list[dict]:
        """
        Retrieve top_k most relevant KB chunks for a query string.
        Returns list of dicts with: id, section, text, score.
        """
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
        full-context LLM injection. Preferred for the complete warehouse report:
        the curated corpus is small enough to inject in full, guaranteeing no
        relevant standard is dropped by top-k retrieval.
        """
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
