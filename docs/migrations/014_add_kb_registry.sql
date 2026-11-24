-- 014_add_kb_registry.sql
--
-- Knowledge-base source registry and chunk store (the serving layer of the
-- ingestion pipeline in app/kb/pipeline). kb/sources.yaml in git is the
-- source of truth for what may be loaded; these tables mirror it and hold the
-- embedded chunks the report agent retrieves from.
--
--   kb_sources  one row per registered source: citation, licence, scope,
--               audience, checksum of the archived original, ingest state
--   kb_chunks   retrievable passages with page and section provenance,
--               a 384-dim embedding and a full-text vector
--
-- Retrieval filters every query through kb_sources (status, warehouse scope,
-- audience), so a passage is only ever served to a caller its source allows.
--
-- Additive and idempotent. The legacy kb_documents table is left untouched.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_sources (
    id               text PRIMARY KEY CHECK (id ~ '^(S[0-9]{2}|W-[A-Z]{3}-[0-9]{2})$'),
    title            text NOT NULL,
    container        text,
    publisher        text NOT NULL,
    authors          text[] NOT NULL DEFAULT '{}',
    edition          text,
    published        text NOT NULL,
    url              text NOT NULL,
    doi              text,
    licence          text NOT NULL,
    licence_url      text,
    attribution      text NOT NULL,
    jurisdiction     text NOT NULL CHECK (jurisdiction IN ('US', 'UK', 'LK', 'INT')),
    doc_type         text NOT NULL,
    applicability    text NOT NULL,
    scope            text NOT NULL DEFAULT 'network' CHECK (scope IN ('network', 'warehouse')),
    warehouse_ids    uuid[] NOT NULL DEFAULT '{}',
    audience         text[] NOT NULL,
    supports         text[] NOT NULL DEFAULT '{}',
    asset_categories text[] NOT NULL DEFAULT '{}',
    components       text[] NOT NULL DEFAULT '{}',
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'withdrawn')),
    review_due       date NOT NULL,
    -- ingest state
    sha256           text,
    version          integer NOT NULL DEFAULT 0,
    pipeline_version text,
    embedding_model  text,
    raw_paths        text[] NOT NULL DEFAULT '{}',
    processed_path   text,
    chunk_count      integer NOT NULL DEFAULT 0,
    retrieved_at     timestamptz,
    ingested_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (scope = 'network' OR cardinality(warehouse_ids) > 0),
    CHECK (cardinality(audience) > 0)
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id              text PRIMARY KEY,
    source_id       text NOT NULL REFERENCES kb_sources (id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    section         text,
    page_start      integer,
    page_end        integer,
    content         text NOT NULL,
    content_hash    text NOT NULL,
    token_count     integer NOT NULL,
    embedding       vector(384) NOT NULL,
    embedding_model text NOT NULL,
    content_tsv     tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(section, '') || ' ' || content)
                    ) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, chunk_index)
);

-- ISBN, report or document numbers, kept for citations.
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS identifiers text[] NOT NULL DEFAULT '{}';

-- Hash of everything that shapes the stored chunks: the original files'
-- checksums, the registry entry, the pipeline version and the embedding
-- model. An unchanged fingerprint means a re-run has nothing to do.
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS fingerprint text;

-- Approximate nearest-neighbour search (cosine). m/ef_construction are the
-- pgvector defaults, which suit a corpus of a few thousand to a few hundred
-- thousand passages.
CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding_hnsw
    ON kb_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_tsv ON kb_chunks USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_source ON kb_chunks (source_id);
CREATE INDEX IF NOT EXISTS ix_kb_sources_status ON kb_sources (status);

-- The legacy corpus had no vector index; every query scanned all rows.
CREATE INDEX IF NOT EXISTS ix_kb_documents_embedding_hnsw
    ON kb_documents USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- The API and the pipeline use the owner role; nothing reaches these tables
-- through Supabase's public REST roles.
ALTER TABLE kb_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_chunks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON kb_sources FROM anon, authenticated;
REVOKE ALL ON kb_chunks FROM anon, authenticated;
