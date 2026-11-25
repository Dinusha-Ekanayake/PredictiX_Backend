"""Knowledge-base retrieval: who may see what, and how results are merged and cited."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.kb.kb_vector_store import _fuse
from app.kb.retrieval import KBHit, KBScope, scope_params, search

WH = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("role, warehouse, expected", [
    ("user", WH, KBScope("user", WH, False)),
    ("admin", WH, KBScope("admin", WH, False)),
    ("admin", None, KBScope("admin", None, False)),              # no warehouse: network sources only
    ("super_admin", WH, KBScope("super_admin", WH, False)),      # warehouse chosen at login
    ("super_admin", None, KBScope("super_admin", None, True)),   # network view
    ("SUPER_ADMIN", None, KBScope("super_admin", None, True)),
])
def test_scope_comes_from_the_signed_in_caller(role, warehouse, expected):
    assert KBScope.for_viewer(SimpleNamespace(role=role), warehouse) == expected


@pytest.mark.parametrize("viewer", [None, SimpleNamespace(role="guest"), SimpleNamespace(role=""), object()])
def test_unknown_callers_get_no_scope(viewer):
    assert KBScope.for_viewer(viewer, WH) is None


def test_only_admins_have_a_network_view():
    assert not KBScope.for_viewer(SimpleNamespace(role="admin"), None).network_view
    assert not KBScope.for_viewer(SimpleNamespace(role="user"), None).network_view


def test_search_without_a_scope_touches_nothing():
    class NoDb:
        def execute(self, *a, **k):
            raise AssertionError("no query may run without a scope")

    assert search(NoDb(), "brake inspection", [0.0] * 384, None) == []
    assert search(NoDb(), "   ", [0.0] * 384, KBScope("user", WH)) == []


def test_scope_is_passed_to_sql_as_bound_parameters():
    assert scope_params(KBScope("user", WH)) == {"role": "user", "network_view": False, "warehouse_id": WH}


def _hit(**kw) -> KBHit:
    base = dict(chunk_id="S07:abc:0001", source_id="S07", title="t", section="§ 1910.178(g) Batteries",
                page_start=None, page_end=None, content="c", url="u", publisher="p", jurisdiction="US",
                doc_type="regulation", applicability="a", licence="l", cosine=0.5, rrf=0.03,
                matched_keywords=True)
    base.update(kw)
    return KBHit(**base)


def test_citations_name_source_section_and_pages():
    assert _hit().citation() == "S07, § 1910.178(g) Batteries"
    assert _hit(section="Section 27", page_start=11, page_end=11).citation() == "S07, Section 27, p. 11"
    assert _hit(section=None, page_start=4, page_end=6).citation() == "S07, pp. 4-6"


def test_fusion_rewards_passages_found_by_both_lists():
    a, b, c = ({"id": x} for x in "abc")
    fused = _fuse([[a, b], [c, b]], top_k=3)
    assert fused[0]["id"] == "b"
    assert {h["id"] for h in fused} == {"a", "b", "c"}
    assert len(_fuse([[a, b], [c]], top_k=2)) == 2


def test_report_prompt_shows_citation_and_applicability_for_each_passage():
    from app.agents.report_agents import _kb_context_lines

    registered = {"corpus": "registry", "citation": "S07, § 1910.178(g) Batteries", "title": "Powered Industrial Trucks",
                  "publisher": "OSHA", "jurisdiction": "US", "applicability": "U.S. rule; reference practice only.",
                  "text": "Battery charging installations shall be located in designated areas.", "id": "S07:x:0001"}
    legacy = {"corpus": "legacy", "tags": ["pdf", "forklift-maintenance-guide.pdf"], "text": "Check forks.", "id": "pdf_1"}
    prompt = "\n".join(_kb_context_lines([registered, legacy]))
    assert "[S07, § 1910.178(g) Batteries] Powered Industrial Trucks (OSHA, US)" in prompt
    assert "Applies: U.S. rule; reference practice only." in prompt
    assert "never Sri Lankan law" in prompt
    assert "[Legacy KB: forklift-maintenance-guide.pdf]" in prompt
