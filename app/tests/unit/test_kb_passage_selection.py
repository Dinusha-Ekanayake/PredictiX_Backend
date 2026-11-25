"""Which retrieved passages reach the answering model.

Regression: "What daily checks should a forklift operator do?" retrieved six
near-duplicate NIOSH case-report chunks (S09) ahead of the HSE passage that
actually lists operator checks (S08, 0.598, ranked 7th). Taking the first four
in rank order handed the model four accident reports, so it answered NOT_FOUND
although the knowledge base covers the question.
"""
from app.ai.agent.kb_answer import MAX_PASSAGES, MAX_PER_SOURCE, SCORE_MARGIN, _select
from app.kb.retrieval import KBHit


def hit(source: str, cosine: float, n: int = 0) -> KBHit:
    return KBHit(
        chunk_id=f"{source}-{n}", source_id=source, title=source, section=None,
        page_start=None, page_end=None, content="", url="", publisher="", jurisdiction="UK",
        doc_type="", applicability="", licence="", cosine=cosine, rrf=0.0, matched_keywords=False,
    )


def test_one_source_cannot_crowd_out_a_relevant_other():
    ranked = [hit("S09", c, i) for i, c in enumerate((0.626, 0.616, 0.547, 0.559, 0.586, 0.597))]
    ranked += [hit("S08", 0.598, 9), hit("S09", 0.591, 10)]

    chosen = _select(ranked)

    assert "S08" in {h.source_id for h in chosen}
    assert len(chosen) == MAX_PASSAGES
    # S09 gets its MAX_PER_SOURCE share plus the back-filled slot S08 left free.
    assert sum(h.source_id == "S09" for h in chosen) == MAX_PASSAGES - 1
    assert MAX_PER_SOURCE < MAX_PASSAGES


def test_a_single_relevant_source_still_fills_the_context():
    ranked = [hit("S08", 0.70 - i * 0.01, i) for i in range(6)]

    chosen = _select(ranked)

    assert len(chosen) == MAX_PASSAGES, "with one source only, the cap must not starve the model"


def test_passages_far_below_the_best_are_not_used():
    chosen = _select([hit("S08", 0.70), hit("S07", 0.70 - SCORE_MARGIN - 0.01)])

    assert [h.source_id for h in chosen] == ["S08"]


def test_rank_order_is_kept():
    ranked = [hit("S09", 0.62, 0), hit("S08", 0.60, 1), hit("S09", 0.61, 2)]

    assert [h.chunk_id for h in _select(ranked)] == ["S09-0", "S08-1", "S09-2"]


def test_nothing_in_nothing_out():
    assert _select([]) == []
