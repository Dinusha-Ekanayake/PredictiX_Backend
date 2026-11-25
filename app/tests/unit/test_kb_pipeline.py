"""Knowledge-base ingestion pipeline: each stage in isolation, no network or database."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.kb.pipeline import store
from app.kb.pipeline.archive import processed_path, raw_path
from app.kb.pipeline.chunking import Chunk, chunk_blocks, drop_duplicates, split_sentences
from app.kb.pipeline.config import MAX_EMBED_TOKENS
from app.kb.pipeline.extract import Block, _is_heading, _signature, extract_ecfr_xml
from app.kb.pipeline.fetch import Artifact, combined_sha256, looks_like
from app.kb.pipeline.ingest import QualityGateError, check_quality, fingerprint
from app.kb.pipeline.references import ieee, render_markdown
from app.kb.pipeline.registry import Registry, Source, load_registry, parse_pages

# ── fixtures ─────────────────────────────────────────────────────────────────


def words(text: str) -> int:
    """Stand-in tokenizer: one token per word, plus two for [CLS]/[SEP]."""
    return len(text.split()) + 2


def source(**overrides) -> Source:
    base = dict(
        id="S99", title="Test Source - Part One", publisher="Test Agency", published="2024",
        url="https://example.gov/doc", fetch=[{"url": "https://example.gov/doc.pdf", "format": "pdf"}],
        licence="Public domain", licence_evidence="Stated on page one of the document.",
        attribution="Test Agency, Test Source.", jurisdiction="US", doc_type="guidance",
        applicability="Reference practice for testing only, not law.", audience=["admin"],
        supports=["chatbot"], asset_categories=["road_vehicle"], components=["brakes"],
        review_due="2027-01-01",
    )
    base.update(overrides)
    return Source.model_validate(base)


# ── registry ─────────────────────────────────────────────────────────────────

def test_the_committed_registry_is_valid():
    registry = load_registry()
    assert registry.active, "the registry must list at least one active source"
    for s in registry.sources:
        assert s.licence_evidence and s.applicability and s.audience


@pytest.mark.parametrize("override, message", [
    ({"id": "X1"}, "id must look like"),
    ({"published": "last year"}, "published must be"),
    ({"warehouses": ["LL-XXX"], "scope": "warehouse"}, "unknown warehouse codes"),
    ({"warehouses": ["LL-COL"]}, "network-scoped source must not list warehouses"),
    ({"scope": "warehouse"}, "must list at least one warehouse"),
    ({"audience": []}, "at least 1"),
    ({"audience": ["guest"]}, "Input should be"),
    ({"fetch": [{"url": "http://insecure.example/doc.pdf", "format": "pdf"}]}, "https"),
    ({"licence_evidence": "yes"}, "at least 10"),
])
def test_registry_rejects_bad_entries(override, message):
    with pytest.raises(ValidationError) as exc:
        source(**override)
    assert message in str(exc.value)


def test_registry_rejects_duplicate_ids():
    entry = source().model_dump(mode="json")
    with pytest.raises(ValidationError, match="duplicate source ids"):
        Registry.model_validate({"registry_version": 1, "sources": [entry, entry]})


def test_page_selection_is_parsed_and_checked():
    assert parse_pages("4-6,10,5") == [4, 5, 6, 10]
    for bad in ("0-3", "5-2", "a-b", "3,,4"):
        with pytest.raises(ValueError):
            parse_pages(bad)


# ── fetch ────────────────────────────────────────────────────────────────────

def test_an_html_error_page_is_not_accepted_as_a_pdf():
    assert looks_like("pdf", b"%PDF-1.7 ...")
    assert not looks_like("pdf", b"<!DOCTYPE html><title>Too many requests</title>")
    assert looks_like("ecfr_xml", b'<?xml version="1.0"?><DIV5>')
    assert not looks_like("ecfr_xml", b"%PDF-1.7")


def test_a_single_file_source_keeps_its_own_checksum():
    content = b"%PDF-1.7 body"
    sha = hashlib.sha256(content).hexdigest()
    art = Artifact("https://x/doc.pdf", "pdf", content, sha, datetime.now(timezone.utc))
    assert combined_sha256([art]) == sha
    assert combined_sha256([art, art]) != sha


# ── extract ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line, mode, expected", [
    ("8.1.6.2. Weibull", "auto", True),
    ("8.1.6.2. Weibull", "multilevel", True),
    ("1. Introduction", "multilevel", False),
    ("6. Practical Considerations.", "auto", True),
    ("OIL ANALYSIS THEORY AND BENEFITS", "auto", True),
    ("ROSEMARY", "auto", False),                                   # a single capitalised word
    ("3 June 1999", "auto", False),                                # a date
    ("3. Immediately following an operation in which any", "auto", False),  # cut-off list item
    ("2. Whenever directed by the unit maintenance officer", "auto", False),
    ("1. Fuel. Use self-service commercial facilities", "auto", False),
    ("OIL ANALYSIS THEORY AND BENEFITS", "none", False),
])
def test_heading_recognition(line, mode, expected):
    assert _is_heading(line, mode) is expected


def test_running_headers_match_regardless_of_spacing_and_page_number():
    assert _signature("NAVAIR 17-15 -50.1 Page 3") == _signature("NAVAIR 17-15-50.1 Page 14")


ECFR = b"""<?xml version="1.0"?>
<DIV8 N="1910.178" TYPE="SECTION"><HEAD>&#xA7; 1910.178 Powered industrial trucks.</HEAD>
<P>(a) <I>General requirements.</I> This section contains safety requirements.</P>
<P>(g) <I>Changing and charging storage batteries.</I> Battery charging installations shall be located in designated areas.</P>
<P>(1) Facilities shall be provided for flushing spilled electrolyte.</P>
<DIV><TABLE><TR><TH>Class</TH><TH>Use</TH></TR><TR><TD>E</TD><TD>Electric</TD></TR></TABLE></DIV>
<CITA>[39 FR 23502]</CITA>
</DIV8>"""


def test_ecfr_sections_tables_and_citations():
    blocks = extract_ecfr_xml(ECFR)
    sections = [b.section for b in blocks]
    assert "§ 1910.178(g) Changing and charging storage batteries" in sections
    # A numbered sub-paragraph stays in its lettered section.
    flushing = next(b for b in blocks if "flushing" in b.text)
    assert flushing.section.endswith("(g) Changing and charging storage batteries")
    assert any("Class | Use" in b.text and "E | Electric" in b.text for b in blocks)
    assert not any("39 FR" in b.text for b in blocks), "source citations are dropped"


# ── chunking ─────────────────────────────────────────────────────────────────

def _blocks(n_sentences: int, section: str = "A", page: int = 1) -> list[Block]:
    text = " ".join(f"Sentence number {i} explains brake inspection practice in detail." for i in range(n_sentences))
    return [Block(text, section, page)]


def test_passages_never_exceed_the_model_limit_and_stay_in_one_section():
    blocks = _blocks(120, "A", 1) + _blocks(60, "B", 2)
    chunks = chunk_blocks(blocks, "Title", words)
    assert len(chunks) > 3
    assert max(c.token_count for c in chunks) <= MAX_EMBED_TOKENS
    for c in chunks:
        assert c.embed_text.startswith(f"Title - {c.section}\n")
        assert c.section in ("A", "B")
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_consecutive_passages_overlap_by_whole_sentences():
    chunks = [c for c in chunk_blocks(_blocks(120), "T", words) if c.section == "A"]
    first_tail = split_sentences(chunks[0].content)[-1]
    assert first_tail in chunks[1].content


def test_a_sentence_longer_than_the_budget_is_split_not_truncated():
    giant = Block(" ".join(["wear"] * 900) + ".", "A", 1)
    chunks = chunk_blocks([giant], "T", words)
    assert sum(c.content.count("wear") for c in chunks) >= 900
    assert max(c.token_count for c in chunks) <= MAX_EMBED_TOKENS


def test_chunking_is_deterministic():
    blocks = _blocks(80)
    assert chunk_blocks(blocks, "T", words) == chunk_blocks(blocks, "T", words)


def test_abbreviations_do_not_end_a_sentence():
    assert split_sentences("Check e.g. brake pads. Then tyres.") == ["Check e.g. brake pads.", "Then tyres."]


def test_duplicates_are_removed_and_the_rest_renumbered():
    c = Chunk(0, "A", 1, 1, "Same text", "h1", 5, "T\nSame text")
    d = Chunk(1, "A", 2, 2, "Other text", "h2", 5, "T\nOther text")
    kept, removed = drop_duplicates([c, c, d])
    assert removed == 1 and [k.index for k in kept] == [0, 1] and kept[1].content == "Other text"


# ── quality gates and idempotency ────────────────────────────────────────────

def _chunk(tokens: int = 100) -> Chunk:
    return Chunk(0, "A", 1, 1, "x", "h", tokens, "T\nx")


def test_quality_gates():
    s = source()
    good = [Block("word " * 400, "A", 1)]
    check_quality(s, good, 1, [_chunk()], 0)
    with pytest.raises(QualityGateError, match="characters extracted"):
        check_quality(s, [Block("tiny", "A", 1)], 1, [_chunk()], 0)
    with pytest.raises(QualityGateError, match="scanned"):
        check_quality(s, good, 50, [_chunk()], 0)
    with pytest.raises(QualityGateError, match="exceed"):
        check_quality(s, good, 1, [_chunk(MAX_EMBED_TOKENS + 1)], 0)
    with pytest.raises(QualityGateError, match="duplicates"):
        check_quality(s, good, 1, [_chunk()], 5)


def test_the_fingerprint_changes_with_anything_that_shapes_the_passages():
    s = source()
    base = fingerprint(s, "sha", "model")
    assert fingerprint(s, "sha", "model") == base
    assert fingerprint(s, "other-sha", "model") != base
    assert fingerprint(s, "sha", "other-model") != base
    with_pages = source(fetch=[{"url": "https://example.gov/doc.pdf", "format": "pdf", "pages": "1-2"}])
    assert fingerprint(with_pages, "sha", "model") != base


def test_an_unchanged_source_is_skipped_and_a_withdrawn_one_is_not():
    state = store.SourceState("fp", "sha", 1, "active")
    assert store.is_up_to_date(state, "fp", "active")
    assert not store.is_up_to_date(state, "fp2", "active")
    assert not store.is_up_to_date(state, "fp", "withdrawn")
    assert not store.is_up_to_date(None, "fp", "active")


def test_chunk_ids_are_stable_and_tied_to_the_version():
    assert store.chunk_id("S01", "abcdef1234567890", 7) == "S01:abcdef123456:0007"


# ── archive and references ───────────────────────────────────────────────────

def test_archive_paths_are_content_addressed():
    art = Artifact("https://x/doc.pdf", "pdf", b"%PDF-", "ab" * 32, datetime.now(timezone.utc))
    assert raw_path("S01", art) == f"raw/S01/{'ab' * 32}.pdf"
    assert processed_path("S01", "fp") == "processed/S01/fp.json"


def test_reference_entries_carry_licence_scope_and_checksum():
    s = source(authors=["A. Author"], doi="10.1/x", identifiers=["No. 5"])
    citation = ieee(s, "2026-11-23")
    assert "A. Author" in citation and "doi: 10.1/x" in citation and "accessed 2026-11-23" in citation
    registry = Registry.model_validate({"registry_version": 1, "sources": [s.model_dump(mode="json")], "excluded": [
        {"id": "X01", "title": "Blocked", "url": "https://x", "reason": "Site refuses robots.", "decided": date(2026, 11, 23)},
    ]})
    md = render_markdown(registry, {"S99": {"status": "active", "version": 1, "chunk_count": 3,
                                            "sha256": "f" * 64, "retrieved_at": datetime(2026, 11, 23)}})
    assert "**[S99]**" in md and "Licence: Public domain" in md and "Audience: admin" in md
    assert "sha256 `ffffffffffffffff...`" in md and "| X01 |" in md
