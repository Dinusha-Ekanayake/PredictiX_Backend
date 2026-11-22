"""Help retrieval logic with fake vectors: no model, no database."""
from __future__ import annotations

import time

import numpy as np
import pytest

import app.chatbot.knowledge_service as ks

FAQS = [
    {"id": 1, "question": "how to log out", "answer": "Use the logout option.", "category": "account", "tags": ["sign out"]},
    {"id": 2, "question": "how to open a ticket", "answer": "Go to Tickets and press New.", "category": "tickets", "tags": None},
    {"id": 3, "question": "what is predictix", "answer": "An asset management system.", "category": "general", "tags": "{overview,about}"},
]


def _unit(v):
    v = np.array(v, dtype=float)
    return v / np.linalg.norm(v)


@pytest.fixture
def faq_index(monkeypatch):
    """An index whose FAQ i points along axis i, so similarity is easy to control."""
    full = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])])
    short = full.copy()
    index = {
        "loaded_at": time.monotonic(),
        "faqs": FAQS,
        "texts": [f"{f['question']}. {f['answer']}" for f in FAQS],
        "vectors": np.stack([full, short]),
    }
    monkeypatch.setattr(ks, "_load_faq_index", lambda db: index)
    return index


@pytest.mark.parametrize("query,expected", [
    ("How do I sign out of PredictiX?", "How do I sign out ?"),
    ("What is PredictiX?", "What is PredictiX?"),
    ("predictix", "predictix"),
    ("reset password in predictix please", "reset password please"),
])
def test_product_name_is_dropped_only_when_content_remains(query, expected):
    assert ks._ranking_query(query) == expected


@pytest.mark.parametrize("raw,tags", [
    (["sign out", "logout"], ["sign out", "logout"]),
    ("{overview,about}", ["overview", "about"]),
    (None, []),
    ("", []),
])
def test_tags_are_read_from_array_or_postgres_text(raw, tags):
    assert ks._as_tags(raw) == tags


def test_semantic_faq_search_ranks_by_similarity_and_labels_hits(faq_index):
    hits = ks.search_faqs(None, "q", 3, list(_unit([0.2, 1.0, 0])))
    assert [h["id"] for h in hits] == [2]  # only FAQ 2 clears the threshold
    assert hits[0]["source"] == "faq" and hits[0]["retrieval"] == "semantic"
    assert hits[0]["title"] == "how to open a ticket"


def test_semantic_faq_search_drops_everything_below_the_threshold(faq_index):
    weak = _unit([1, 1, 1]) * 0.0 + _unit([0.25, 0.25, 0.94])  # mostly axis 2
    hits = ks.search_faqs(None, "q", 3, list(weak))
    assert all(h["similarity"] >= ks.MIN_SEMANTIC_SIMILARITY for h in hits)


def test_faq_search_falls_back_to_keywords_without_a_vector(faq_index):
    hits = ks.search_faqs(None, "open a new ticket", 3, None)
    assert hits and hits[0]["id"] == 2 and hits[0]["retrieval"] == "lexical"


def test_help_search_merges_sources_and_sorts_by_score(monkeypatch):
    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _Session())
    monkeypatch.setattr(ks, "embed_text", lambda q: [1.0])
    monkeypatch.setattr(ks, "search_faqs", lambda db, q, k, v: [
        {"title": "faq a", "content": "x", "similarity": 0.5, "source": "faq"}])
    monkeypatch.setattr(ks, "_semantic_articles", lambda db, v, k: [
        {"title": "article b", "content": "y", "similarity": 0.8}])
    hits = ks.search_help("anything useful", 4)
    assert [h["title"] for h in hits] == ["article b", "faq a"]
    assert hits[0]["source"] == "article"


def test_help_search_uses_keywords_when_embedding_fails(monkeypatch):
    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    def boom(q):
        raise RuntimeError("no model")

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _Session())
    monkeypatch.setattr(ks, "embed_text", boom)
    seen = {}
    monkeypatch.setattr(ks, "search_faqs", lambda db, q, k, v: seen.setdefault("vector", v) and [] or [])
    monkeypatch.setattr(ks, "_lexical_search", lambda db, q, k: [{"title": "kw", "content": "c", "similarity": 0.2}])
    hits = ks.search_help("how do I log out", 3)
    assert seen["vector"] is None and hits[0]["title"] == "kw"


def test_empty_or_blank_queries_return_nothing():
    assert ks.search_help("") == [] and ks.search_help("   ") == []


def test_threshold_matches_the_measured_value():
    # Chosen with scripts/eval_rag.py and gated by app/tests/eval; changing it
    # should be a deliberate, re-measured decision.
    assert ks.MIN_SEMANTIC_SIMILARITY == pytest.approx(0.30)
