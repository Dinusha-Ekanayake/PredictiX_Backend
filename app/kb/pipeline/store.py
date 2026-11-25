"""Write a source and its passages to the serving tables, atomically.

Each source is replaced in one transaction: its registry row is upserted,
its old passages deleted and the new ones inserted. Readers see either the
old version or the new one, never a half-loaded source. A transaction-level
advisory lock stops two ingest runs writing at the same time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chatbot.knowledge_service import embedding_literal
from app.kb.pipeline.chunking import Chunk
from app.kb.pipeline.registry import Source

_LOCK_KEY = "predictix_kb_ingest"


@dataclass(frozen=True)
class SourceState:
    fingerprint: Optional[str]
    sha256: Optional[str]
    version: int
    status: str


def current_state(db: Session, source_id: str) -> Optional[SourceState]:
    row = db.execute(
        text("SELECT fingerprint, sha256, version, status FROM kb_sources WHERE id = :id"), {"id": source_id},
    ).mappings().first()
    return SourceState(row["fingerprint"], row["sha256"], row["version"], row["status"]) if row else None


def is_up_to_date(state: Optional[SourceState], fingerprint: str, status: str) -> bool:
    """True when the stored source already matches everything that shapes it."""
    return state is not None and state.fingerprint == fingerprint and state.status == status


def warehouse_ids(db: Session, codes: list[str]) -> list[str]:
    if not codes:
        return []
    rows = db.execute(text("SELECT code, id::text AS id FROM warehouses WHERE code = ANY(:codes)"),
                      {"codes": codes}).mappings().all()
    found = {r["code"]: r["id"] for r in rows}
    missing = sorted(set(codes) - set(found))
    if missing:
        raise ValueError(f"warehouse codes not in the database: {missing}")
    return [found[c] for c in codes]


def chunk_id(source_id: str, fingerprint: str, index: int) -> str:
    return f"{source_id}:{fingerprint[:12]}:{index:04d}"


_UPSERT_SOURCE = text("""
INSERT INTO kb_sources (
    id, title, container, publisher, authors, edition, identifiers, published, url, doi,
    licence, licence_url, attribution, jurisdiction, doc_type, applicability,
    scope, warehouse_ids, audience, supports, asset_categories, components, status, review_due,
    sha256, fingerprint, version, pipeline_version, embedding_model, raw_paths, processed_path,
    chunk_count, retrieved_at, ingested_at, updated_at
) VALUES (
    :id, :title, :container, :publisher, :authors, :edition, :identifiers, :published, :url, :doi,
    :licence, :licence_url, :attribution, :jurisdiction, :doc_type, :applicability,
    :scope, CAST(:warehouse_ids AS uuid[]), :audience, :supports, :asset_categories, :components, :status, :review_due,
    :sha256, :fingerprint, 1, :pipeline_version, :embedding_model, :raw_paths, :processed_path,
    :chunk_count, :retrieved_at, now(), now()
)
ON CONFLICT (id) DO UPDATE SET
    title = EXCLUDED.title, container = EXCLUDED.container, publisher = EXCLUDED.publisher,
    authors = EXCLUDED.authors, edition = EXCLUDED.edition, identifiers = EXCLUDED.identifiers,
    published = EXCLUDED.published, url = EXCLUDED.url, doi = EXCLUDED.doi,
    licence = EXCLUDED.licence, licence_url = EXCLUDED.licence_url, attribution = EXCLUDED.attribution,
    jurisdiction = EXCLUDED.jurisdiction, doc_type = EXCLUDED.doc_type, applicability = EXCLUDED.applicability,
    scope = EXCLUDED.scope, warehouse_ids = EXCLUDED.warehouse_ids, audience = EXCLUDED.audience,
    supports = EXCLUDED.supports, asset_categories = EXCLUDED.asset_categories, components = EXCLUDED.components,
    status = EXCLUDED.status, review_due = EXCLUDED.review_due,
    -- the version counts changes to the original document, not re-processing
    version = kb_sources.version + CASE WHEN kb_sources.sha256 IS DISTINCT FROM EXCLUDED.sha256 THEN 1 ELSE 0 END,
    sha256 = EXCLUDED.sha256, fingerprint = EXCLUDED.fingerprint,
    pipeline_version = EXCLUDED.pipeline_version, embedding_model = EXCLUDED.embedding_model,
    raw_paths = EXCLUDED.raw_paths, processed_path = EXCLUDED.processed_path,
    chunk_count = EXCLUDED.chunk_count, retrieved_at = EXCLUDED.retrieved_at,
    ingested_at = now(), updated_at = now()
""")

# Passages are written with multi-row INSERTs (psycopg2 execute_values): one
# round trip per batch instead of one per row, which matters on a high-latency
# link to the database.
_INSERT_CHUNKS = (
    "INSERT INTO kb_chunks (id, source_id, chunk_index, section, page_start, page_end, "
    "content, content_hash, token_count, embedding, embedding_model, warehouse_id) VALUES %s"
)
_CHUNK_TEMPLATE = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s::uuid)"
_INSERT_BATCH = 200


def replace_source(
    db: Session,
    source: Source,
    *,
    sha256: str,
    fingerprint: str,
    pipeline_version: str,
    embedding_model: str,
    raw_paths: list[str],
    processed_path: str,
    retrieved_at: datetime,
    chunks: list[Chunk],
    vectors: list[list[float]],
) -> None:
    """Upsert the source row and swap in its passages in one transaction."""
    if len(chunks) != len(vectors):
        raise ValueError("every passage needs exactly one vector")
    # If the client dies mid-load, the server ends the transaction (rolling it
    # back) instead of holding the lock and the half-written rows open.
    db.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
    db.execute(text("SET LOCAL statement_timeout = '120s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _LOCK_KEY})
    db.execute(_UPSERT_SOURCE, {
        "id": source.id, "title": source.title, "container": source.container,
        "publisher": source.publisher, "authors": source.authors, "edition": source.edition,
        "identifiers": source.identifiers, "published": source.published, "url": source.url,
        "doi": source.doi, "licence": source.licence, "licence_url": source.licence_url,
        "attribution": source.attribution, "jurisdiction": source.jurisdiction,
        "doc_type": source.doc_type, "applicability": source.applicability, "scope": source.scope,
        "warehouse_ids": warehouse_ids(db, source.warehouses), "audience": list(source.audience),
        "supports": list(source.supports), "asset_categories": list(source.asset_categories),
        "components": list(source.components), "status": source.status, "review_due": source.review_due,
        "sha256": sha256, "fingerprint": fingerprint, "pipeline_version": pipeline_version,
        "embedding_model": embedding_model, "raw_paths": raw_paths, "processed_path": processed_path,
        "chunk_count": len(chunks), "retrieved_at": retrieved_at,
    })
    db.execute(text("DELETE FROM kb_chunks WHERE source_id = :id"), {"id": source.id})
    rows = [
        (chunk_id(source.id, fingerprint, c.index), source.id, c.index, c.section, c.page_start,
         c.page_end, c.content, c.content_hash, c.token_count, embedding_literal(v), embedding_model,
         c.warehouse_id)
        for c, v in zip(chunks, vectors)
    ]
    from psycopg2.extras import execute_values

    # Same connection and transaction as the statements above.
    cursor = db.connection().connection.cursor()
    try:
        execute_values(cursor, _INSERT_CHUNKS, rows, template=_CHUNK_TEMPLATE, page_size=_INSERT_BATCH)
    finally:
        cursor.close()


def set_status(db: Session, source_id: str, status: str) -> bool:
    """Withdraw or reinstate a source without deleting its record. True if a row changed."""
    result = db.execute(
        text("UPDATE kb_sources SET status = :s, updated_at = now() WHERE id = :id AND status <> :s"),
        {"id": source_id, "s": status},
    )
    return result.rowcount > 0


def stored_sources(db: Session) -> list[dict]:
    return [dict(r) for r in db.execute(text(
        "SELECT id, status, version, sha256, fingerprint, chunk_count, retrieved_at, ingested_at "
        "FROM kb_sources ORDER BY id"
    )).mappings().all()]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
