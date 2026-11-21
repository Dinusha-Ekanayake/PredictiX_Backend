"""Embeddings and retrieval for the chatbot knowledge base (table knowledge_base).

Embeddings are all-MiniLM-L6-v2 (384 dimensions), the model the stored vectors
were made with. A query is embedded by the first of these that works:

1. the local sentence-transformers model, if it is installed and cached
   (main.py keeps the Hugging Face hub offline, so it is never downloaded at
   request time);
2. the hosted Hugging Face feature-extraction endpoint.

Retrieval is cosine similarity in Postgres over active articles only, with a
relevance threshold, so an unrelated article is never handed to the model as
if it answered the question. If no embedding can be made, the same active
articles are searched by keyword (TF-IDF) instead, and each hit says which
method found it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import requests
from sqlalchemy import text

log = logging.getLogger("predictix.knowledge")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MAX_EMBED_CHARS = 2000

# Measured on this knowledge base: articles that answer the question score
# 0.44 to 0.77, off-topic questions score at most 0.14.
MIN_SEMANTIC_SIMILARITY = 0.25
MIN_LEXICAL_SCORE = 0.10
_LEXICAL_CACHE_SECONDS = 300

_DEFAULT_EMBEDDING_URL = (
    f"https://router.huggingface.co/hf-inference/models/{EMBEDDING_MODEL}"
    "/pipeline/feature-extraction"
)
_RETIRED_HOST = "api-inference.huggingface.co"

_model_lock = threading.Lock()
_local_model = None
_local_model_failed = False


def _embedding_url() -> str:
    """Hosted endpoint, replacing a configured value that points at the retired host."""
    configured = os.getenv("HF_INFERENCE_API_URL")
    if not configured:
        return _DEFAULT_EMBEDDING_URL
    if _RETIRED_HOST in configured:
        log.warning(
            "HF_INFERENCE_API_URL points at the retired host %s; using %s instead.",
            _RETIRED_HOST, _DEFAULT_EMBEDDING_URL,
        )
        return _DEFAULT_EMBEDDING_URL
    return configured


def _get_local_model():
    """The local sentence-transformers model, loaded once, or None if unavailable."""
    global _local_model, _local_model_failed
    if _local_model is not None or _local_model_failed:
        return _local_model
    with _model_lock:
        if _local_model is None and not _local_model_failed:
            try:
                from sentence_transformers import SentenceTransformer

                _local_model = SentenceTransformer(EMBEDDING_MODEL.split("/", 1)[1])
                log.info("Local embedding model %s loaded.", EMBEDDING_MODEL)
            except Exception as exc:  # not installed, or not in the local cache
                _local_model_failed = True
                log.warning("Local embedding model unavailable (%s); using the hosted endpoint.", exc)
    return _local_model


def _embed_hosted(value: str) -> list[float]:
    headers = {}
    if token := os.getenv("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(
        _embedding_url(), headers=headers,
        json={"inputs": [value], "options": {"wait_for_model": True}},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HF embedding API returned {response.status_code}: {response.text[:200]}")
    vector = response.json()[0]
    if len(vector) != EMBEDDING_DIM:
        raise RuntimeError(f"HF embedding API returned {len(vector)} dimensions, expected {EMBEDDING_DIM}")
    return [float(x) for x in vector]


def embed_text(value: str) -> list[float]:
    """384-dim embedding for `value`. Raises if no embedding source works."""
    value = (value or "")[:MAX_EMBED_CHARS]
    model = _get_local_model()
    if model is not None:
        return [float(x) for x in model.encode(value, normalize_embeddings=True)]
    return _embed_hosted(value)


def embedding_literal(vector: list[float]) -> str:
    """pgvector text form of a vector, for use with CAST(:v AS vector)."""
    return "[" + ",".join(f"{x:.7f}" for x in vector) + "]"


# ── Keyword fallback ──────────────────────────────────────────────────────────

_lexical_lock = threading.Lock()
_lexical_index: Optional[tuple[float, list[dict], object, object]] = None


def _active_articles(db) -> list[dict]:
    rows = db.execute(text(
        "SELECT id, title, content, category FROM knowledge_base WHERE is_active"
    )).mappings().all()
    return [dict(r) for r in rows]


def _lexical_search(db, query: str, match_count: int) -> list[dict]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    global _lexical_index
    with _lexical_lock:
        if _lexical_index is None or time.monotonic() - _lexical_index[0] > _LEXICAL_CACHE_SECONDS:
            articles = _active_articles(db)
            if not articles:
                return []
            vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
            matrix = vectorizer.fit_transform(f"{a['title']}. {a['content']}" for a in articles)
            _lexical_index = (time.monotonic(), articles, vectorizer, matrix)
        _, articles, vectorizer, matrix = _lexical_index

    scores = cosine_similarity(vectorizer.transform([query]), matrix)[0]
    ranked = sorted(range(len(articles)), key=lambda i: scores[i], reverse=True)[:match_count]
    return [
        {**articles[i], "similarity": float(scores[i]), "retrieval": "lexical"}
        for i in ranked if scores[i] >= MIN_LEXICAL_SCORE
    ]


def invalidate_lexical_index() -> None:
    """Drop the keyword index so the next fallback search sees article edits."""
    global _lexical_index
    with _lexical_lock:
        _lexical_index = None


# ── Retrieval ─────────────────────────────────────────────────────────────────

def search_knowledge(query: str, match_count: int = 3) -> list[dict]:
    """Active knowledge-base articles relevant to `query`, most relevant first.

    Each hit has id, title, content, category, similarity and retrieval
    ("semantic" or "lexical"). Returns [] when nothing is relevant or the
    knowledge base cannot be reached.
    """
    from app.db.session import SessionLocal

    query = (query or "").strip()[:MAX_EMBED_CHARS]
    if not query:
        return []
    match_count = max(1, min(int(match_count), 10))

    try:
        with SessionLocal() as db:
            try:
                vector = embed_text(query)
            except Exception as exc:
                log.warning("Query embedding failed (%s); using keyword search.", exc)
                return _lexical_search(db, query, match_count)

            rows = db.execute(text(
                "SELECT id, title, content, category, "
                "       1 - (embedding <=> CAST(:v AS vector)) AS similarity "
                "FROM knowledge_base "
                "WHERE is_active AND embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:v AS vector) "
                "LIMIT :k"
            ), {"v": embedding_literal(vector), "k": match_count}).mappings().all()
            return [
                {**dict(r), "similarity": float(r["similarity"]), "retrieval": "semantic"}
                for r in rows if float(r["similarity"]) >= MIN_SEMANTIC_SIMILARITY
            ]
    except Exception as exc:
        # Non-fatal: the assistant still answers from its database tools.
        log.error("Knowledge search failed (%s): %s", type(exc).__name__, exc)
        return []
