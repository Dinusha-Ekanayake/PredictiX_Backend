"""Retrieval quality and access scoping of the registered knowledge base, on the live database.

Runs against the passages the pipeline loaded (python -m app.kb.pipeline ingest).
Gates:
  * hit@3 on the golden questions is at least HIT_AT_3_FLOOR
  * no passage from a source outside the caller's audience is ever returned
  * off-topic questions return no registered passage
Run:  pytest -m eval app/tests/eval/test_kb_registry_eval.py -s
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.eval

GOLDEN = json.loads((Path(__file__).parents[1] / "data" / "kb_golden.json").read_text(encoding="utf-8"))
HIT_AT_3_FLOOR = 0.85
WAREHOUSE = None  # network-scoped corpus; warehouse scoping is covered by the leak test below


@pytest.fixture(scope="module")
def searcher():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from app.chatbot.knowledge_service import embed_text
    from app.db.session import SessionLocal
    from app.kb.retrieval import KBScope, search

    def run(question: str, role: str, top_k: int = 5):
        scope = KBScope(role=role, warehouse_id=WAREHOUSE, network_view=(role == "super_admin"))
        with SessionLocal() as db:
            if not db.execute(__import__("sqlalchemy").text("SELECT count(*) FROM kb_chunks")).scalar():
                pytest.skip("the registered knowledge base is empty; run the ingest pipeline first")
            return search(db, question, embed_text(question), scope, top_k=top_k)

    return run


def test_golden_questions_find_their_source(searcher):
    rows, hits = [], 0
    for case in GOLDEN["retrieval"]:
        found = [h.source_id for h in searcher(case["q"], case["role"])]
        ok = case["expect"] in found[:3]
        hits += ok
        rows.append(f"{'PASS' if ok else 'MISS'}  {case['expect']}  top={found[:3]}  {case['q']}")
    rate = hits / len(GOLDEN["retrieval"])
    print("\n" + "\n".join(rows) + f"\nhit@3 = {hits}/{len(GOLDEN['retrieval'])} = {rate:.2f}")
    assert rate >= HIT_AT_3_FLOOR


def test_no_source_reaches_a_role_outside_its_audience(searcher):
    for case in GOLDEN["audience"]:
        found = {h.source_id for h in searcher(case["q"], case["role"], top_k=10)}
        assert not found & set(case["forbid"]), f"{case['role']} saw {found & set(case['forbid'])} for {case['q']!r}"


def test_off_topic_questions_return_no_registered_passage(searcher):
    for case in GOLDEN["off_topic"]:
        found = searcher(case["q"], case["role"])
        assert not found, f"{case['q']!r} returned {[(h.source_id, round(h.cosine, 2)) for h in found]}"


def test_a_warehouse_scoped_source_never_reaches_another_warehouse():
    """Inserts a temporary source scoped to one warehouse inside a transaction
    that is rolled back, and checks the other warehouses cannot retrieve it."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from sqlalchemy import text

    from app.chatbot.knowledge_service import embed_text, embedding_literal
    from app.db.session import SessionLocal
    from app.kb.retrieval import KBScope, search

    phrase = "Galle port yard salt corrosion check for brake lines"
    with SessionLocal() as db:
        ids = dict(db.execute(text("SELECT code, id::text FROM warehouses")).all())
        if not {"LL-COL", "LL-GLE"} <= ids.keys():
            pytest.skip("expected warehouses are not present")
        db.execute(text("""
            INSERT INTO kb_sources (id, title, publisher, published, url, licence, attribution, jurisdiction,
                doc_type, applicability, scope, warehouse_ids, audience, review_due, status)
            VALUES ('W-GLE-99', 'Leak test', 'Test', '2026', 'https://example.invalid', 'internal', 'internal test',
                'LK', 'internal_sop', 'Temporary row for the scope leak test.', 'warehouse',
                ARRAY[CAST(:gle AS uuid)], ARRAY['user','admin','super_admin'], '2027-01-01', 'active')
        """), {"gle": ids["LL-GLE"]})
        db.execute(text("""
            INSERT INTO kb_chunks (id, source_id, chunk_index, content, content_hash, token_count, embedding, embedding_model)
            VALUES ('W-GLE-99:test:0000', 'W-GLE-99', 0, :c, 'leaktest', 20, CAST(:v AS vector), 'test')
        """), {"c": phrase, "v": embedding_literal(embed_text(phrase))})
        try:
            def sources(role, wh, network=False):
                return {h.source_id for h in search(db, phrase, embed_text(phrase), KBScope(role, wh, network), top_k=10)}

            assert "W-GLE-99" in sources("user", ids["LL-GLE"])
            assert "W-GLE-99" not in sources("user", ids["LL-COL"])
            assert "W-GLE-99" not in sources("admin", ids["LL-COL"])
            assert "W-GLE-99" not in sources("admin", None)
            assert "W-GLE-99" in sources("super_admin", None, network=True)
        finally:
            db.rollback()


def test_ticket_patterns_stay_in_their_warehouse():
    """D01 passages are about one warehouse each: an admin finds their own
    warehouse's patterns and never another warehouse's; users see none (audience)."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL is not set")
    from sqlalchemy import text

    from app.chatbot.knowledge_service import embed_text
    from app.db.session import SessionLocal
    from app.kb.retrieval import KBScope, search

    question = "Is brake noise on descents a recurring issue at our warehouse and how long does it take to fix?"
    vector = embed_text(question)
    with SessionLocal() as db:
        if not db.execute(text("SELECT count(*) FROM kb_chunks WHERE source_id = 'D01'")).scalar():
            pytest.skip("D01 is not loaded")
        ids = dict(db.execute(text("SELECT code, id::text FROM warehouses")).all())
        passage_wh = dict(db.execute(text("SELECT id, warehouse_id::text FROM kb_chunks WHERE source_id = 'D01'")).all())
        for code, wh in ids.items():
            hits = [h for h in search(db, question, vector, KBScope("admin", wh), top_k=10) if h.source_id == "D01"]
            assert hits, f"admin at {code} found no ticket patterns"
            assert {passage_wh[h.chunk_id] for h in hits} == {wh}, f"admin at {code} saw another warehouse's patterns"
        assert not [h for h in search(db, question, vector, KBScope("user", ids["LL-COL"]), top_k=10)
                    if h.source_id == "D01"], "users are outside D01's audience"
        network = {passage_wh[h.chunk_id] for h in search(db, question, vector, KBScope("super_admin", None, True), top_k=20)
                   if h.source_id == "D01"}
        assert len(network) > 1, "the super admin network view should see several warehouses"
