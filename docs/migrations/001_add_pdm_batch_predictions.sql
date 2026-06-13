-- Migration: Add pdm_batch_predictions table
-- Run this in Supabase SQL editor or via psql

CREATE TABLE IF NOT EXISTS pdm_batch_predictions (
    id                                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id                          UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,

    -- Classification
    failure_probability               NUMERIC(10, 4),
    maintenance_required              BOOLEAN,
    risk_level                        TEXT,

    -- Regression
    predicted_days_until_maintenance  INTEGER,
    predicted_maintenance_date        DATE,

    -- Health score
    health_score                      NUMERIC(10, 4),
    health_status                     TEXT,
    contributing_factors              JSONB DEFAULT '[]'::jsonb,

    -- Cost estimation
    estimated_cost_lkr                NUMERIC(12, 2),
    min_cost_lkr                      NUMERIC(12, 2),
    max_cost_lkr                      NUMERIC(12, 2),

    -- SHAP / feature explanations
    top_explanations                  JSONB DEFAULT '[]'::jsonb,

    -- Run metadata
    predicted_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_duration_ms                   INTEGER,
    error_message                     TEXT,
    status                            TEXT NOT NULL DEFAULT 'ok',

    -- One row per asset (upsert target)
    UNIQUE (asset_id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_pdm_batch_predictions_asset_id
    ON pdm_batch_predictions (asset_id);

CREATE INDEX IF NOT EXISTS idx_pdm_batch_predictions_predicted_at
    ON pdm_batch_predictions (predicted_at DESC);

CREATE INDEX IF NOT EXISTS idx_pdm_batch_predictions_health_score
    ON pdm_batch_predictions (health_score);

CREATE INDEX IF NOT EXISTS idx_pdm_batch_predictions_risk_level
    ON pdm_batch_predictions (risk_level);

-- Enable Row Level Security (Supabase best practice)
ALTER TABLE pdm_batch_predictions ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read predictions
CREATE POLICY "Allow authenticated read" ON pdm_batch_predictions
    FOR SELECT TO authenticated USING (true);

-- Allow service role full access (used by the backend)
CREATE POLICY "Allow service role full access" ON pdm_batch_predictions
    FOR ALL TO service_role USING (true) WITH CHECK (true);
