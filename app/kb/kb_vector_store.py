"""
PredictiX KB Vector Store
===========================
Retrieval for the warehouse report agent over two corpora:

* the registered knowledge base (kb_sources / kb_chunks), loaded by the
  ingestion pipeline in app.kb.pipeline from kb/sources.yaml. Searched by
  app.kb.retrieval: hybrid (vector + full text) and filtered by the caller's
  role and warehouse. Without a scope it returns nothing.
* the legacy corpus (kb_documents), PDFs loaded before the registry existed,
  pending an audit of their licences. Ranked by cosine similarity, with a
  TF-IDF fallback when no query embedding can be made.

The query is embedded once with the same all-MiniLM-L6-v2 model both corpora
were embedded with, and the two ranked lists are merged by reciprocal rank
fusion.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text

from app.chatbot.knowledge_service import embed_text, embedding_literal
from app.db.session import SessionLocal
from app.kb.retrieval import KBScope
from app.kb.retrieval import search as kb_search

log = logging.getLogger("predictix.kb_vector_store")

_RRF_K = 60


def _legacy_filter() -> str:
    """SQL condition limiting the legacy corpus to what may be served.

    The kb_* rows are the team's own knowledge-base articles. The pdf_* rows
    come from ten PDFs loaded before the source registry, with no recorded
    publisher or licence; they are excluded until audited (kb/LEGACY_AUDIT.md),
    unless KB_LEGACY_PDFS_ENABLED=true. The condition is a constant, never
    built from input.
    """
    import os

    if os.getenv("KB_LEGACY_PDFS_ENABLED", "false").strip().lower() == "true":
        return "TRUE"
    return r"id NOT LIKE 'pdf\_%'"


def _fuse(ranked_lists: list[list[dict]], top_k: int) -> list[dict]:
    """Merge ranked lists by reciprocal rank fusion; ties keep list order."""
    scored: dict[str, tuple[float, int, dict]] = {}
    order = 0
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            prev = scored.get(hit["id"])
            score = (prev[0] if prev else 0.0) + 1.0 / (_RRF_K + rank)
            scored[hit["id"]] = (score, prev[1] if prev else order, hit)
            order += 1
    ranked = sorted(scored.values(), key=lambda t: (-t[0], t[1]))
    return [hit for _, _, hit in ranked[:top_k]]


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
                    rows = db.execute(text(
                        f"SELECT id, text, tags FROM kb_documents WHERE {_legacy_filter()}"
                    )).mappings().all()
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

    def retrieve(
        self,
        query: str,
        top_k: int = 4,
        min_score: float = 0.25,
        *,
        scope: Optional[KBScope] = None,
    ) -> list[dict]:
        """Top `top_k` passages for `query`, best first.

        Two corpora are searched: the registered sources (kb_chunks, hybrid
        search, filtered by `scope`; nothing is returned from it without a
        scope) and the legacy kb_documents corpus. The two ranked lists are
        merged by reciprocal rank fusion. The query and every returned
        passage (corpus, source, citation, score) go into the current AI trace.
        """
        try:
            vector = embed_text(query)
        except Exception as e:
            log.warning("Query embedding failed (%s); using keyword search over kb_documents.", e)
            vector = None

        registered = self._registered(query, vector, scope, top_k) if vector is not None else []
        legacy = self._retrieve(query, top_k, min_score, vector)
        hits = _fuse([registered, legacy], top_k)

        from app.ai.agent.tracing import record

        record(
            "retrieval",
            corpus="kb_chunks+kb_documents",
            method="hybrid+semantic" if vector is not None else "lexical",
            query=query,
            threshold=min_score,
            scope={"role": scope.role, "warehouse_id": scope.warehouse_id, "network_view": scope.network_view}
            if scope else None,
            hits=[
                {"id": h["id"], "corpus": h["corpus"], "source": h.get("source_id"),
                 "citation": h.get("citation"), "score": round(h["score"], 4)}
                for h in hits
            ],
        )
        return hits

    def _registered(self, query: str, vector: list[float], scope: Optional[KBScope], top_k: int) -> list[dict]:
        if scope is None:
            return []
        try:
            with SessionLocal() as db:
                found = kb_search(db, query, vector, scope, top_k=top_k)
        except Exception as e:
            log.warning("Registered knowledge base search failed (%s); using the legacy corpus only.", e)
            return []
        return [
            {
                "id": h.chunk_id,
                "section": h.citation(),
                "citation": h.citation(),
                "text": h.content,
                "tags": [h.source_id],
                "score": h.cosine,
                "retrieval": "hybrid",
                "corpus": "registry",
                "source_id": h.source_id,
                "title": h.title,
                "publisher": h.publisher,
                "url": h.url,
                "jurisdiction": h.jurisdiction,
                "doc_type": h.doc_type,
                "applicability": h.applicability,
            }
            for h in found
        ]

    def _retrieve(self, query: str, top_k: int, min_score: float, vector: Optional[list[float]] = None) -> list[dict]:
        if vector is None:
            return [{**h, "corpus": "legacy"} for h in self._lexical(query, top_k, min_score=0.05)]
        return [{**h, "corpus": "legacy"} for h in self._semantic(vector, query, top_k, min_score)]

    def _semantic(self, vector: list[float], query: str, top_k: int, min_score: float) -> list[dict]:

        try:
            with SessionLocal() as db:
                rows = db.execute(text(
                    "SELECT id, text, tags, 1 - (embedding <=> CAST(:v AS vector)) AS score "
                    f"FROM kb_documents WHERE embedding IS NOT NULL AND {_legacy_filter()} "
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
