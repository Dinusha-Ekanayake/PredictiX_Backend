-- 013_add_ai_traces.sql
--
-- Audit trail for AI answers. One row per chatbot reply or AI warehouse
-- report, holding the question, the answer, and the ordered steps that
-- produced it: routing, retrieval hits with scores, model calls, generated
-- SQL and its sandbox outcome, actions taken. Written by
-- app/ai/agent/tracing.py and read through GET /chatbot/traces.
--
-- Additive and idempotent: creates the table and its indexes only if missing.

CREATE TABLE IF NOT EXISTS ai_traces (
    id            uuid PRIMARY KEY,
    created_at    timestamptz NOT NULL DEFAULT now(),
    channel       text NOT NULL,                 -- 'chatbot' or 'report'
    user_id       uuid,
    role          text,
    warehouse_id  uuid,
    question      text,
    intent        text,
    answer        text,
    status        text NOT NULL DEFAULT 'ok',
    duration_ms   integer,
    steps         jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_ai_traces_created_at ON ai_traces (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_traces_user ON ai_traces (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_traces_warehouse ON ai_traces (warehouse_id, created_at DESC);

-- The API reads this table with the owner role; nothing should reach it
-- through Supabase's public REST roles.
ALTER TABLE ai_traces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ai_traces FROM anon, authenticated;
