"""Retrieval-quality gate for chatbot help search (FAQs + knowledge base).

Runs every question in app/tests/data/rag_golden.json through search_help
against the real database and embedding model, and fails when quality drops
below the gates. The held-out split was written after tuning and never used
to choose the threshold, so it measures generalisation; the tuning split guards
against regressions on the cases the design was built around.

    pytest app/tests/eval -m eval -s      # prints the per-question report
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.eval

DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "rag_golden.json").read_text(encoding="utf-8"))

# Regression gates: a little below the measured scores, so normal noise in the
# corpus does not fail the build but a real drop does.
MIN_HIT_AT_1 = {"tuning": 0.90, "heldout": 0.80}
MIN_HIT_AT_3 = {"tuning": 0.95, "heldout": 0.90}
MIN_REJECTION = 0.90


def _matches(hit: dict, expected: list[str]) -> bool:
    title = str(hit.get("title", "")).lower()
    return any(e.lower() in title for e in expected)


@pytest.fixture(scope="module")
def search():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from app.chatbot.knowledge_service import embed_text, search_help

    try:
        embed_text("probe")
    except Exception as exc:  # no local model and no hosted credits
        pytest.skip(f"no embedding source available: {exc}")
    return search_help


@pytest.fixture(scope="module")
def results(search):
    rows = []
    for item in DATA["answerable"]:
        hits = search(item["q"], 3)
        rows.append({
            **item,
            "hit1": bool(hits) and _matches(hits[0], item["expected"]),
            "hit3": any(_matches(h, item["expected"]) for h in hits),
            "top": f"{hits[0]['source']}:{hits[0]['title'][:40]} ({hits[0]['similarity']:.2f})" if hits else "nothing",
        })
    negatives = [(q, search(q, 3)) for q in DATA["off_topic"]]
    _print_report(rows, negatives)
    return rows, negatives


def _print_report(rows, negatives):
    print("\nRAG retrieval evaluation")
    for r in rows:
        mark = "OK  " if r["hit1"] else ("~3  " if r["hit3"] else "MISS")
        print(f"  {mark} [{r['split']:7}] {r['q'][:55]:55} -> {r['top']}")
    for q, hits in negatives:
        print(f"  {'OK  ' if not hits else 'LEAK'} [negative] {q[:55]:55} -> "
              f"{hits[0]['title'][:40] + ' (%.2f)' % hits[0]['similarity'] if hits else 'nothing'}")


def _rate(rows, split, key):
    subset = [r for r in rows if r["split"] == split]
    return sum(r[key] for r in subset) / len(subset)


@pytest.mark.parametrize("split", ["tuning", "heldout"])
def test_top_result_is_correct_often_enough(results, split):
    rows, _ = results
    rate = _rate(rows, split, "hit1")
    assert rate >= MIN_HIT_AT_1[split], f"{split} hit@1 {rate:.0%} < {MIN_HIT_AT_1[split]:.0%}"


@pytest.mark.parametrize("split", ["tuning", "heldout"])
def test_correct_answer_is_in_the_top_three(results, split):
    rows, _ = results
    rate = _rate(rows, split, "hit3")
    assert rate >= MIN_HIT_AT_3[split], f"{split} hit@3 {rate:.0%} < {MIN_HIT_AT_3[split]:.0%}"


def test_off_topic_questions_retrieve_nothing(results):
    """Questions sharing no subject with the help content. Hard negatives that
    mention PredictiX subjects are checked at the answer step instead
    (test_llm_answers.py)."""
    _, negatives = results
    rejected = sum(1 for _, hits in negatives if not hits) / len(negatives)
    leaks = [q for q, hits in negatives if hits]
    assert rejected >= MIN_REJECTION, f"off-topic rejection {rejected:.0%}; leaked: {leaks}"


def test_every_hit_carries_source_and_score(search):
    for hit in search("how do I open a ticket", 4):
        assert hit["source"] in {"faq", "article"}
        assert 0.0 <= hit["similarity"] <= 1.0
        assert hit["title"] and hit["content"]
