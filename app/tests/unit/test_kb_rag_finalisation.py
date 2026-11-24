"""Privacy, derived ticket patterns, the chatbot knowledge answer and its guards. No network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.kb.pipeline.chunking import chunk_blocks
from app.kb.pipeline.extract import Block
from app.kb.pipeline.internal import blocks_from_ticket_patterns
from app.kb.pipeline.privacy import Redactor, redact
from app.kb.pipeline.registry import FetchSpec
from app.kb.retrieval import KBHit

WH_A, WH_B = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def words(text: str) -> int:
    return len(text.split()) + 2


# ── privacy ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, gone", [
    ("Call me on 077 123 4567 after 5", "077 123 4567"),
    ("Phone +94 77 123 4567", "+94 77 123 4567"),
    ("Office 011-2345678", "011-2345678"),
    ("Mail nimal.perera@lankalogix.com today", "nimal.perera@lankalogix.com"),
    ("NIC 199012345678 attached", "199012345678"),
    ("Old NIC 901234567V", "901234567V"),
])
def test_personal_data_is_removed(raw, gone):
    assert gone not in redact(raw)


def test_staff_names_are_removed_and_plates_kept():
    out = Redactor(["Nimal Perera", "Al"])("Nimal Perera checked WP LE-8317; nimal perera signed. Al was there.")
    assert "Nimal" not in out and "nimal" not in out
    assert "WP LE-8317" in out
    assert "Al was there" in out, "names shorter than five characters are not matched (too many false hits)"


# ── derived ticket patterns ──────────────────────────────────────────────────

def _snapshot() -> bytes:
    pattern = {
        "first_month": "2024-01", "last_month": "2025-06", "categories": [["mechanical", 90]],
        "priorities": [["high", 60], ["medium", 40]], "median_days_to_resolve": 3.5,
        "vehicles": [["Isuzu ELF", 7]], "asset_categories": ["road_vehicle"], "active": 1, "done": 9,
        "tickets": 10, "issue": "Oil pressure warning on the cluster.", "title": "Oil pressure warning",
    }
    return json.dumps({"format": "db_ticket_patterns", "data_up_to": "2025-06-30", "patterns": [
        {**pattern, "warehouse_id": WH_A, "warehouse": "LankaLogix - Colombo"},
        {**pattern, "warehouse_id": WH_B, "warehouse": "LankaLogix - Galle", "tickets": 3},
    ]}).encode()


def test_each_pattern_becomes_a_passage_tagged_with_its_warehouse():
    blocks = blocks_from_ticket_patterns(_snapshot())
    assert [b.warehouse_id for b in blocks] == [WH_A, WH_B]
    colombo = blocks[0].text
    assert "10 tickets" in colombo and "Median time to resolve: 3.5 days" in colombo and "Isuzu ELF (7)" in colombo
    assert blocks[0].section == "LankaLogix - Colombo - Oil pressure warning"


def test_a_passage_never_mixes_two_warehouses():
    blocks = [Block("Same issue text. " * 5, "Same section", None, WH_A),
              Block("Same issue text. " * 5, "Same section", None, WH_B)]
    chunks = chunk_blocks(blocks, "T", words)
    assert {c.warehouse_id for c in chunks} == {WH_A, WH_B}
    assert all(c.warehouse_id in (WH_A, WH_B) for c in chunks)


@pytest.mark.parametrize("spec, ok", [
    ({"format": "db_ticket_patterns"}, True),
    ({"format": "db_ticket_patterns", "url": "https://x/doc"}, False),
    ({"format": "pdf"}, False),
])
def test_internal_formats_take_no_url_and_documents_need_one(spec, ok):
    if ok:
        assert FetchSpec.model_validate(spec).internal
    else:
        with pytest.raises(Exception):
            FetchSpec.model_validate(spec)


# ── chatbot knowledge answer ─────────────────────────────────────────────────

def _hit(source_id="S07", jurisdiction="US", cosine=0.6, **kw) -> KBHit:
    base = dict(chunk_id=f"{source_id}:x:0001", source_id=source_id, title="Powered Industrial Trucks",
                section="§ 1910.178(g) Batteries", page_start=None, page_end=None,
                content="Battery charging installations shall be located in designated areas.",
                url="https://www.ecfr.gov", publisher="OSHA", jurisdiction=jurisdiction, doc_type="regulation",
                applicability="U.S. rule; reference practice only.", licence="Public domain",
                cosine=cosine, rrf=0.03, matched_keywords=True)
    base.update(kw)
    return KBHit(**base)


@pytest.fixture()
def kb(monkeypatch):
    import app.ai.agent.guardrails as guardrails
    import app.ai.agent.kb_answer as kb_answer
    import app.chatbot.knowledge_service as ks

    state = {"hits": [], "reply": "Charge batteries in a designated area [S07].", "messages": None}
    monkeypatch.setattr(ks, "embed_text", lambda q: [0.0] * 384)
    monkeypatch.setattr(kb_answer, "search", lambda db, q, v, scope, top_k=8: list(state["hits"]))

    def fake_llm(*, messages, **kw):
        state["messages"] = messages
        return state["reply"], ""

    monkeypatch.setattr(guardrails, "call_groq", fake_llm)
    return state


def _ask(question, role="user", warehouse=WH_A):
    from app.ai.agent.kb_answer import answer_from_kb

    return answer_from_kb(question, SimpleNamespace(role=role), warehouse, db=object())


def test_answers_cite_sources_listed_by_code(kb):
    kb["hits"] = [_hit()]
    out = _ask("How should forklift batteries be charged?")
    assert "[S07]" in out["answer"]
    assert "\U0001f4ce *Sources:*" in out["answer"] and "(OSHA, United States)" in out["answer"]
    from app.ai.agent.guardrails import PROMPT_GUARD

    assert kb["messages"][0]["content"] == PROMPT_GUARD
    assert "<kb_passages>" in kb["messages"][-1]["content"]
    assert "Applies: U.S. rule" in kb["messages"][-1]["content"]


def test_a_local_law_question_is_never_answered_from_a_foreign_rule(kb):
    kb["hits"] = [_hit(jurisdiction="US", cosine=0.7)]
    out = _ask("Is a fitness certificate compulsory for lorries in Sri Lanka?")
    assert "don't have an official Sri Lankan source" in out["answer"]
    assert kb["messages"] is None, "the model must not be called with only foreign rules"


def test_a_local_law_question_uses_sri_lankan_sources_only(kb):
    kb["hits"] = [_hit("S01", "US", 0.7), _hit("S13", "LK", 0.65, title="Factories Ordinance", section="Section 29")]
    kb["reply"] = "The safe working load must be marked [S13]."
    out = _ask("Is it a legal requirement to mark the safe working load?", role="admin")
    prompt = kb["messages"][-1]["content"]
    assert "[S13]" in prompt and "[S01]" not in prompt
    assert "Factories Ordinance" in out["answer"]


def test_model_not_found_reply_becomes_an_honest_not_covered(kb):
    kb["hits"], kb["reply"] = [_hit()], "NOT_FOUND"
    assert "couldn't find that" in _ask("How do I calibrate a tachograph?")["answer"]


def test_no_relevant_passage_returns_none_so_help_can_answer(kb):
    kb["hits"] = []
    assert _ask("How do I change my avatar?") is None


def test_an_unknown_caller_searches_nothing(kb):
    from app.ai.agent.kb_answer import answer_from_kb

    kb["hits"] = [_hit()]
    assert answer_from_kb("battery charging", SimpleNamespace(role="guest"), WH_A, db=object()) is None


def test_weak_passages_far_below_the_best_are_not_used(kb):
    kb["hits"] = [_hit("S07", cosine=0.70), _hit("S09", cosine=0.40, title="NIOSH Alert")]
    _ask("How should forklift batteries be charged?")
    assert "NIOSH Alert" not in kb["messages"][-1]["content"]


def test_model_down_falls_back_to_the_top_passage(kb, monkeypatch):
    import app.ai.agent.guardrails as guardrails

    def down(**kw):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(guardrails, "call_groq", down)
    kb["hits"] = [_hit()]
    out = _ask("battery charging")
    assert "Battery charging installations" in out["answer"] and "[S07]" in out["answer"]


# ── coverage-gap report ──────────────────────────────────────────────────────

def test_gap_report_lists_weak_searches_most_asked_first():
    from app.kb.gaps import gap_report

    now = datetime.now(timezone.utc)
    steps = [
        (now, "chatbot", {"kind": "retrieval", "corpus": "kb_chunks", "query": "Coolant too hot?", "hits": [{"score": 0.21}]}),
        (now, "chatbot", {"kind": "retrieval", "corpus": "kb_chunks", "query": "coolant too hot?", "hits": []}),
        (now, "chatbot", {"kind": "retrieval", "corpus": "kb_chunks", "query": "Tyre pressure", "hits": [{"score": 0.8}]}),
        (now - timedelta(days=1), "report", {"kind": "retrieval", "corpus": "kb_chunks", "query": "Emission test law",
                                              "local_law_question": True, "hits": [{"score": 0.3}]}),
    ]

    class Db:
        def execute(self, *a, **k):
            return SimpleNamespace(all=lambda: steps)

    report = gap_report(Db(), days=30)
    rows = [l for l in report.splitlines() if l.startswith("| ") and "Times" not in l]
    assert rows[0].startswith("| 2 | 0.21 | coolant too hot?")
    assert not any("tyre pressure" in r for r in rows)
    assert "1 of those asked about legal requirements" in report


# ── legacy corpus gate ───────────────────────────────────────────────────────

def test_unaudited_legacy_pdfs_are_off_by_default(monkeypatch):
    from app.kb.kb_vector_store import _legacy_filter

    monkeypatch.delenv("KB_LEGACY_PDFS_ENABLED", raising=False)
    assert "NOT LIKE 'pdf" in _legacy_filter()
    monkeypatch.setenv("KB_LEGACY_PDFS_ENABLED", "true")
    assert _legacy_filter() == "TRUE"


# ── routing between app help and the maintenance knowledge base ──────────────

@pytest.mark.parametrize("question, help_hit, expected", [
    ("How do I change my avatar?", {"source": "faq", "similarity": 0.8}, "help"),
    # A team article is maintenance content, not app help: the knowledge base answers.
    ("How should forklift batteries be charged?", {"source": "article", "similarity": 0.8}, "kb"),
    # A legal question must pass the jurisdiction guard even with a strong FAQ match.
    ("Is an emission test compulsory in Sri Lanka?", {"source": "faq", "similarity": 0.9}, "kb"),
    ("How often should brakes be inspected?", {"source": "faq", "similarity": 0.4}, "kb"),
])
def test_knowledge_questions_are_routed_correctly(monkeypatch, question, help_hit, expected):
    import app.ai.agent.kb_answer as kb_answer
    import app.ai.agent.tools as tools
    import app.chatbot.knowledge_service as ks

    monkeypatch.setattr(ks, "search_help", lambda q, match_count=4: [{**help_hit, "title": "t", "content": "c"}])
    monkeypatch.setattr(kb_answer, "answer_from_kb", lambda *a, **k: {"answer": "kb", "action_buttons": []})
    monkeypatch.setattr(tools, "answer_from_help", lambda q, ctx, hits: {"answer": "help", "action_buttons": []})
    ctx = tools.ToolContext(db=object(), user=SimpleNamespace(id="u", role="admin", warehouse_id=WH_A))
    assert tools.handle_knowledge(question, ctx)["answer"] == expected


def test_knowledge_base_failure_falls_back_to_help(monkeypatch):
    import app.ai.agent.kb_answer as kb_answer
    import app.ai.agent.tools as tools
    import app.chatbot.knowledge_service as ks

    def broken(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(ks, "search_help", lambda q, match_count=4: [])
    monkeypatch.setattr(kb_answer, "answer_from_kb", broken)
    monkeypatch.setattr(tools, "answer_from_help", lambda q, ctx, hits: {"answer": "help", "action_buttons": []})
    ctx = tools.ToolContext(db=object(), user=SimpleNamespace(id="u", role="admin", warehouse_id=WH_A))
    assert tools.handle_knowledge("brake wear", ctx)["answer"] == "help"


# ── uploaded internal documents ──────────────────────────────────────────────

def _w_source(**over):
    from app.kb.pipeline.registry import Source

    base = dict(
        id="W-GLE-01", title="Galle route profile", publisher="LankaLogix Galle", published="2026",
        url="predictix://kb/W-GLE-01",
        fetch=[{"storage_path": "incoming/galle/route-profile.md", "format": "markdown"}],
        licence="Internal", licence_evidence="Written by the Galle warehouse team for PredictiX.",
        attribution="LankaLogix Galle warehouse.", jurisdiction="LK", doc_type="internal_sop",
        applicability="Applies to the Galle warehouse fleet only.", scope="warehouse", warehouses=["LL-GLE"],
        audience=["user", "admin"], supports=["chatbot"], asset_categories=["road_vehicle"],
        components=["brakes"], review_due="2027-06-01",
    )
    base.update(over)
    return Source.model_validate(base)


def test_a_warehouse_document_can_be_loaded_from_private_storage():
    assert _w_source().fetch[0].storage_path == "incoming/galle/route-profile.md"


@pytest.mark.parametrize("over, message", [
    ({"id": "S50"}, "only W- internal sources"),
    ({"scope": "network", "warehouses": []}, "must be scoped to its warehouse"),
    ({"fetch": [{"storage_path": "incoming/../raw/S01/x.pdf", "format": "pdf"}]}, "storage_path must look like"),
    ({"fetch": [{"storage_path": "raw/S01/x.pdf", "format": "pdf"}]}, "storage_path must look like"),
    ({"fetch": [{"url": "https://x/doc.md", "format": "markdown"}]}, "uploaded internal documents only"),
    ({"fetch": [{"url": "https://x/doc.pdf", "storage_path": "incoming/g/a.pdf", "format": "pdf"}]}, "exactly one"),
])
def test_uploaded_documents_are_restricted(over, message):
    with pytest.raises(Exception) as exc:
        _w_source(**over)
    assert message in str(exc.value)


def test_uploads_are_verified_before_use():
    from app.kb.pipeline.fetch import FetchError, from_storage
    from app.kb.pipeline.registry import FetchSpec

    class Store:
        def __init__(self, data):
            self.data = data

        def read(self, path):
            return self.data

    md = FetchSpec.model_validate({"storage_path": "incoming/g/a.md", "format": "markdown"})
    art = from_storage(md, Store(b"# Title\nText"))
    assert art.url == "kb-sources:incoming/g/a.md" and len(art.sha256) == 64
    with pytest.raises(FetchError, match="not a markdown file"):
        from_storage(md, Store(b"<!DOCTYPE html><p>error</p>"))
    pdf = FetchSpec.model_validate({"storage_path": "incoming/g/a.pdf", "format": "pdf"})
    with pytest.raises(FetchError, match="not a pdf file"):
        from_storage(pdf, Store(b"plain text"))


def test_markdown_headings_become_sections_and_list_items_sentences():
    from app.kb.pipeline.extract import extract_markdown

    blocks = extract_markdown(b"# Route\n\nSalt air **daily**.\n\n## Checks\n- Rinse brake lines\n- Inspect terminals\n")
    assert [(b.section, b.text) for b in blocks] == [
        ("Route", "Salt air daily."), ("Checks", "Rinse brake lines. Inspect terminals"),
    ]
