-- 015_kb_passage_scope.sql
--
-- Passage-level warehouse scope for the knowledge base.
--
-- A source derived from operational data (for example D01, ticket issue
-- patterns) holds passages about different warehouses. Each passage carries
-- the warehouse it describes; retrieval shows it only to callers in that
-- warehouse (and to a super admin's network view). NULL means the passage
-- follows its source's scope, which is the case for every published document.
--
-- Also allows source ids of the form D01 (derived from PredictiX data).
-- Additive and idempotent.

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS warehouse_id uuid REFERENCES warehouses (id);
CREATE INDEX IF NOT EXISTS ix_kb_chunks_warehouse ON kb_chunks (warehouse_id) WHERE warehouse_id IS NOT NULL;

ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_id_check;
ALTER TABLE kb_sources ADD CONSTRAINT kb_sources_id_check
    CHECK (id ~ '^(S[0-9]{2}|D[0-9]{2}|W-[A-Z]{3}-[0-9]{2})$');
