"""Run the pipeline for one source: fetch, extract, chunk, check, embed, archive, store.

Order matters. Everything that can fail cheaply (download, parsing, quality
gates) runs before the expensive and irreversible steps, and the database is
written last, in one transaction, only after the original has been archived.
A failure in any step leaves the previously loaded version of the source in
place and untouched.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.kb.pipeline import store
from app.kb.pipeline.archive import Archive
from app.kb.pipeline.chunking import Chunk, chunk_blocks, drop_duplicates
from app.kb.pipeline.config import (
    MAX_DUPLICATE_CHUNK_RATIO,
    MAX_EMBED_TOKENS,
    MIN_CHARS_PER_PDF_PAGE,
    MIN_SOURCE_CHARS,
    PIPELINE_VERSION,
)
from app.kb.pipeline.embedding import Embedder
from app.kb.pipeline.extract import Block, extract
from app.kb.pipeline.fetch import Artifact, combined_sha256, fetch, from_storage, snapshot
from app.kb.pipeline.registry import Source, parse_pages

log = logging.getLogger("predictix.kb.ingest")


class QualityGateError(RuntimeError):
    """The source's extracted content failed a quality check."""


@dataclass
class SourceReport:
    source_id: str
    outcome: str = "pending"          # ingested | unchanged | planned | failed
    detail: str = ""
    sha256: str = ""
    fingerprint: str = ""
    pages: int = 0
    blocks: int = 0
    characters: int = 0
    chunks: int = 0
    duplicates_removed: int = 0
    max_tokens: int = 0
    mean_tokens: float = 0.0
    sections: int = 0
    raw_paths: list[str] = field(default_factory=list)
    processed_path: str = ""


def fingerprint(source: Source, sha256: str, embedding_model: str) -> str:
    """Hash of everything that shapes the stored passages of `source`."""
    entry = source.model_dump(mode="json")
    payload = json.dumps(
        {"sha256": sha256, "entry": entry, "pipeline": PIPELINE_VERSION, "model": embedding_model},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def check_quality(source: Source, blocks: list[Block], pdf_pages: int, chunks: list[Chunk], duplicates: int) -> None:
    characters = sum(len(b.text) for b in blocks)
    if characters < MIN_SOURCE_CHARS:
        raise QualityGateError(f"only {characters} characters extracted")
    if pdf_pages and characters / pdf_pages < MIN_CHARS_PER_PDF_PAGE:
        raise QualityGateError(
            f"{characters / pdf_pages:.0f} characters per page; the PDF may be scanned images without text")
    if not chunks:
        raise QualityGateError("no passages produced")
    too_long = [c.index for c in chunks if c.token_count > MAX_EMBED_TOKENS]
    if too_long:
        raise QualityGateError(f"passages {too_long[:5]} exceed {MAX_EMBED_TOKENS} tokens")
    total = len(chunks) + duplicates
    if total and duplicates / total > MAX_DUPLICATE_CHUNK_RATIO:
        raise QualityGateError(f"{duplicates} of {total} passages are duplicates; extraction is likely broken")


def _processed_payload(source: Source, artifacts: list[Artifact], fp: str, blocks: list[Block], chunks: list[Chunk]) -> dict:
    return {
        "source_id": source.id,
        "fingerprint": fp,
        "pipeline_version": PIPELINE_VERSION,
        "originals": [{"url": a.url, "sha256": a.sha256, "retrieved_at": a.retrieved_at.isoformat()} for a in artifacts],
        "blocks": [asdict(b) for b in blocks],
        "chunks": [{k: v for k, v in asdict(c).items() if k != "embed_text"} for c in chunks],
    }


def ingest_source(
    source: Source,
    *,
    embedder: Embedder,
    db_factory,
    archive: Optional[Archive],
    dry_run: bool,
    force: bool = False,
    refresh: bool = False,
) -> SourceReport:
    report = SourceReport(source.id)

    # 1. Fetch every file of the source and verify it.
    def _get(spec) -> Artifact:
        if spec.internal:
            return snapshot(spec, db_factory)
        if spec.storage_path:
            if archive is None:
                raise RuntimeError("reading an uploaded document needs the private storage archive")
            return from_storage(spec, archive)
        return fetch(spec, refresh=refresh)

    artifacts = [_get(spec) for spec in source.fetch]
    report.sha256 = combined_sha256(artifacts)
    fp = fingerprint(source, report.sha256, embedder.model_name)
    report.fingerprint = fp

    if not force and not dry_run:
        with db_factory() as db:
            if store.is_up_to_date(store.current_state(db, source.id), fp, source.status):
                report.outcome = "unchanged"
                report.detail = "fingerprint matches the stored version"
                return report

    # 2. Extract text with page and section provenance.
    blocks: list[Block] = []
    pdf_pages = 0
    for spec, artifact in zip(source.fetch, artifacts):
        extracted = extract(spec.format, artifact.content, spec.pages, spec.headings)
        if spec.include_sections is not None:
            extracted = [b for b in extracted if b.section in spec.include_sections]
        blocks.extend(extracted)
        if spec.format == "pdf":
            pdf_pages += len(parse_pages(spec.pages)) if spec.pages else _pdf_page_count(artifact.content)

    # 3. Chunk, de-duplicate, check quality.
    chunks, duplicates = drop_duplicates(chunk_blocks(blocks, source.short_title, embedder.count_tokens))
    check_quality(source, blocks, pdf_pages, chunks, duplicates)

    report.pages = pdf_pages
    report.blocks = len(blocks)
    report.characters = sum(len(b.text) for b in blocks)
    report.chunks = len(chunks)
    report.duplicates_removed = duplicates
    report.max_tokens = max(c.token_count for c in chunks)
    report.mean_tokens = round(sum(c.token_count for c in chunks) / len(chunks), 1)
    report.sections = len({c.section for c in chunks})

    if dry_run:
        report.outcome = "planned"
        return report

    # 4. Embed. Done before archiving so a model failure leaves no orphan files.
    vectors = embedder.embed([c.embed_text for c in chunks])

    # 5. Archive the originals and the processed text. Nothing is served
    #    unless its original is preserved.
    if archive is None:
        raise RuntimeError("an archive is required for a real ingest")
    report.raw_paths = [archive.put_raw(source.id, a) for a in artifacts]
    report.processed_path = archive.put_processed(source.id, fp, _processed_payload(source, artifacts, fp, blocks, chunks))

    # 6. Swap the source's rows in one transaction.
    with db_factory() as db:
        store.replace_source(
            db, source,
            sha256=report.sha256, fingerprint=fp, pipeline_version=PIPELINE_VERSION,
            embedding_model=embedder.model_name, raw_paths=report.raw_paths,
            processed_path=report.processed_path,
            retrieved_at=min(a.retrieved_at for a in artifacts),
            chunks=chunks, vectors=vectors,
        )
        db.commit()
    report.outcome = "ingested"
    return report


def _pdf_page_count(content: bytes) -> int:
    import io

    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(content)).pages)
