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
import re
import threading
import time
from typing import Optional

import requests
from sqlalchemy import text

log = logging.getLogger("predictix.knowledge")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MAX_EMBED_CHARS = 2000

# Measured with scripts/eval_rag.py: correct FAQ and article hits score 0.41 to
# 0.79, off-topic questions at most 0.14, and the one wrong top hit 0.25.
MIN_SEMANTIC_SIMILARITY = 0.30
MIN_LEXICAL_SCORE = 0.10
_LEXICAL_CACHE_SECONDS = 300
# FAQ writes refresh the FAQ index directly, so this is only a safety net.
_FAQ_CACHE_SECONDS = 3600

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
        return [float(x) for x in model.encode(value, normalize_embeddings=True, show_progress_bar=False)]
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


# ── FAQ index ─────────────────────────────────────────────────────────────────
# The faqs table has no embedding column, so the 30-odd active FAQs are embedded
# here with the same model and kept in memory. Any FAQ write calls
# invalidate_faq_index(), and the index also expires after a few minutes.

_faq_lock = threading.Lock()
_faq_index: Optional[dict] = None


def invalidate_faq_index() -> None:
    global _faq_index
    with _faq_lock:
        _faq_index = None


def _load_faq_index(db) -> dict:
    global _faq_index
    with _faq_lock:
        if _faq_index is not None and time.monotonic() - _faq_index["loaded_at"] <= _FAQ_CACHE_SECONDS:
            return _faq_index
        rows = db.execute(text(
            "SELECT id, question, answer, category, tags FROM faqs WHERE is_active"
        )).mappings().all()
        faqs = [dict(r) for r in rows]
        # Tags often hold the synonyms people actually type ("sign out" for
        # "log out"), so they are embedded with the question and answer.
        texts = [
            f"{f['question']}. {f['answer']} {' '.join(_as_tags(f.get('tags')))}".strip()
            for f in faqs
        ]
        # Each FAQ gets two vectors: the full question and answer, and a short
        # "question; tag; tag" text. A short user question lines up best with
        # the short form, where the synonyms are not drowned out by the answer.
        # A query scores against whichever vector is closer.
        short_texts = ["; ".join([f["question"], *_as_tags(f.get("tags"))]) for f in faqs]
        vectors = None
        try:
            if texts:
                import numpy as np

                vectors = np.stack([
                    np.array([embed_text(t) for t in texts]),
                    np.array([embed_text(t) for t in short_texts]),
                ])
        except Exception as exc:
            log.warning("FAQ embedding failed (%s); FAQs will use keyword search.", exc)
            vectors = None
        _faq_index = {"loaded_at": time.monotonic(), "faqs": faqs, "texts": texts, "vectors": vectors}
        return _faq_index


def _as_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw if t]
    if isinstance(raw, str) and raw.strip():
        return [t.strip() for t in raw.strip("{}").split(",") if t.strip()]
    return []


def warm_up() -> None:
    """Load the embedding model and build the FAQ index ahead of the first
    question, so that question does not wait for them. Safe to call from a
    background thread; failures only mean the first question does the work."""
    from app.db.session import SessionLocal

    try:
        embed_text("warm up")
        with SessionLocal() as db:
            _load_faq_index(db)
        log.info("Help search warmed up.")
    except Exception as exc:
        log.warning("Help search warm-up skipped: %s", exc)


def search_faqs(db, query: str, match_count: int, query_vector: Optional[list[float]]) -> list[dict]:
    """Active FAQs relevant to `query`, most relevant first."""
    index = _load_faq_index(db)
    faqs = index["faqs"]
    if not faqs:
        return []
    if query_vector is not None and index["vectors"] is not None:
        import numpy as np

        scores = (index["vectors"] @ np.array(query_vector)).max(axis=0)
        threshold, method = MIN_SEMANTIC_SIMILARITY, "semantic"
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        matrix = vectorizer.fit_transform(index["texts"])
        scores = cosine_similarity(vectorizer.transform([query]), matrix)[0]
        threshold, method = MIN_LEXICAL_SCORE, "lexical"
    ranked = sorted(range(len(faqs)), key=lambda i: float(scores[i]), reverse=True)[:match_count]
    return [
        {
            "id": faqs[i]["id"],
            "title": faqs[i]["question"],
            "content": faqs[i]["answer"],
            "category": faqs[i].get("category"),
            "similarity": float(scores[i]),
            "retrieval": method,
            "source": "faq",
        }
        for i in ranked
        if float(scores[i]) >= threshold
    ]


_PRODUCT_NAME_RE = re.compile(r"\b(?:(?:in|of|on|for|with|to|into|from|use|using)\s+)?predictix\b", re.IGNORECASE)


_FILLER_WORDS = frozenset(
    "a an the is are was what whats how do does did can could i me my you your we "
    "it this that to of in on for and or please tell about".split()
)


def _ranking_query(query: str) -> str:
    """The query with the product name removed, unless that leaves no content.

    "What is PredictiX?" keeps the name, because without it nothing is left to
    match; "How do I sign out of PredictiX?" drops it.
    """
    stripped = _PRODUCT_NAME_RE.sub(" ", query)
    content = [w for w in re.findall(r"[a-z0-9]+", stripped.lower()) if w not in _FILLER_WORDS]
    return " ".join(stripped.split()) if content else query


def search_help(query: str, match_count: int = 4) -> list[dict]:
    """Help content for `query` from the FAQs and the knowledge base together.

    Both sources are ranked on the same similarity scale and merged, so the
    answer is built from whichever is most relevant. Each hit carries a
    `source` of "faq" or "article". Returns [] when nothing is relevant.
    """
    from app.db.session import SessionLocal

    query = (query or "").strip()[:MAX_EMBED_CHARS]
    if not query:
        return []
    match_count = max(1, min(int(match_count), 10))
    # Every help item is about PredictiX, so the product name carries no
    # meaning for ranking, yet it pulls a query toward any answer that happens
    # to name the product ("sign out of PredictiX" matched the 2FA answer).
    # A query that is only about the product keeps it.
    ranking_query = _ranking_query(query)
    try:
        vector = embed_text(ranking_query)
    except Exception as exc:
        log.warning("Query embedding failed (%s); using keyword search.", exc)
        vector = None

    hits: list[dict] = []
    try:
        with SessionLocal() as db:
            hits.extend(search_faqs(db, query, match_count, vector))
            if vector is None:
                articles = _lexical_search(db, query, match_count)
            else:
                articles = _semantic_articles(db, vector, match_count)
            hits.extend({**a, "source": "article"} for a in articles)
    except Exception as exc:
        log.error("Help search failed (%s): %s", type(exc).__name__, exc)
        return []
    hits.sort(key=lambda h: h["similarity"], reverse=True)
    hits = hits[:match_count]
    _trace_retrieval("faqs+knowledge_base", query, ranking_query, vector is not None, hits)
    return hits


def _trace_retrieval(corpus: str, query: str, ranking_query: str, semantic: bool, hits: list[dict]) -> None:
    from app.ai.agent.tracing import record

    record(
        "retrieval",
        corpus=corpus,
        method="semantic" if semantic else "keyword (embedding unavailable)",
        query=query,
        ranking_query=ranking_query,
        threshold=MIN_SEMANTIC_SIMILARITY if semantic else MIN_LEXICAL_SCORE,
        hits=[
            {"source": h.get("source", "article"), "id": str(h.get("id")), "title": h.get("title"),
             "score": round(float(h.get("similarity", 0.0)), 4)}
            for h in hits
        ],
    )


def _semantic_articles(db, vector: list[float], match_count: int) -> list[dict]:
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
            return _semantic_articles(db, vector, match_count)
    except Exception as exc:
        # Non-fatal: the assistant still answers from its database tools.
        log.error("Knowledge search failed (%s): %s", type(exc).__name__, exc)
        return []
