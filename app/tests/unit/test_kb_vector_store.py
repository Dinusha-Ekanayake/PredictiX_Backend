"""KBVectorStore retrieval.

The empty-index guard in retrieve() must test `self._matrix is None`. A scipy
sparse matrix has no single truth value, so `if not self._matrix` raises
ValueError instead of answering the question, and every call fails once
documents are loaded.

These tests fit a real TF-IDF index over a small in-memory corpus, so they need
no database and no network.
"""
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from app.kb.kb_vector_store import KBVectorStore

CORPUS = [
    {"id": "a", "section": "Ops: PM coverage", "text":
        "Preventive maintenance should account for seventy percent of all work orders.",
        "tags": ["preventive", "pm"], "source": "SMRP"},
    {"id": "b", "section": "Policy: risk benchmarks", "text":
        "A fleet with more than five percent of assets in a critical band is high risk.",
        "tags": ["critical", "risk"], "source": "ISO 55000"},
    {"id": "c", "section": "Ops: service intervals", "text":
        "Forklifts are serviced every two hundred and fifty engine hours.",
        "tags": ["service", "forklift"], "source": "Manual"},
]


def _loaded_store() -> KBVectorStore:
    """A store with its index already fitted, bypassing the Supabase load."""
    store = KBVectorStore()
    store._docs = CORPUS
    store._ids = [d["id"] for d in CORPUS]
    store._texts = [d["text"] for d in CORPUS]
    store._tags = [d["tags"] for d in CORPUS]
    store._vectorizer = TfidfVectorizer(
        strip_accents="unicode", lowercase=True, stop_words="english",
        ngram_range=(1, 2), max_features=2000, sublinear_tf=True,
    )
    store._matrix = store._vectorizer.fit_transform(store._texts)
    return store


def test_retrieve_does_not_raise_on_a_fitted_sparse_matrix():
    # The regression itself: a populated index must not make the guard throw.
    store = _loaded_store()
    hits = store.retrieve("preventive maintenance coverage", top_k=2)
    assert isinstance(hits, list)


def test_retrieve_returns_the_relevant_document_first():
    store = _loaded_store()
    hits = store.retrieve("how often are forklifts serviced", top_k=3)
    assert hits, "retrieval returned nothing for a question the corpus answers"
    assert hits[0]["id"] == "c", f"expected the service-interval doc first, got {hits[0]['id']}"


def test_retrieve_respects_top_k():
    store = _loaded_store()
    assert len(store.retrieve("maintenance", top_k=1)) <= 1
    assert len(store.retrieve("maintenance", top_k=3)) <= 3


def test_retrieve_returns_empty_when_nothing_is_indexed():
    """An empty corpus leaves _matrix as None, which must read as "no index"
    rather than raising or being mistaken for a fitted one."""
    store = KBVectorStore()
    store._docs = []
    store._texts = []
    store._vectorizer = None
    store._matrix = None
    assert store.retrieve("anything") == []


def test_scores_are_attached_and_ordered():
    store = _loaded_store()
    hits = store.retrieve("critical band fleet risk", top_k=3)
    assert hits, "retrieval returned nothing"
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True), f"scores are not ranked: {scores}"
    assert all(0.0 <= s <= 1.0 for s in scores), f"cosine scores outside 0..1: {scores}"
