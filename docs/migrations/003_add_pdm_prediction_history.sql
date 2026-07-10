-- Migration: Add pdm_prediction_history table
-- Run this in Supabase SQL editor or via psql
--
-- Append-only log of every batch prediction run, never upserted or
-- overwritten — unlike pdm_batch_predictions (which only ever holds the
-- latest row per asset). Exists so that predictions made today can
-- eventually be checked against what actually happened afterward (a real
-- maintenance_events row within N days, an unplanned "repair" event, etc.).
-- The backend must only ever INSERT into this table, never UPDATE/DELETE.

CREATE TABLE IF NOT EXISTS pdm_prediction_history (
    id                                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id                          UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,

    failure_probability               NUMERIC(10, 4),
    predicted_days_until_maintenance  INTEGER,
    predicted_maintenance_date        DATE,
    health_score                      NUMERIC(10, 4),
    tier                              TEXT,
    model_version                     TEXT,

    predicted_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for the validation queries this table exists to support: "what
-- did we predict for this asset, and when" / "what were all predictions in
-- a given window, to join against maintenance_events afterward".
CREATE INDEX IF NOT EXISTS idx_pdm_prediction_history_asset_id
    ON pdm_prediction_history (asset_id);

CREATE INDEX IF NOT EXISTS idx_pdm_prediction_history_predicted_at
    ON pdm_prediction_history (predicted_at DESC);

CREATE INDEX IF NOT EXISTS idx_pdm_prediction_history_asset_predicted_at
    ON pdm_prediction_history (asset_id, predicted_at DESC);

-- Enable Row Level Security (Supabase best practice)
ALTER TABLE pdm_prediction_history ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read prediction history
CREATE POLICY "Allow authenticated read" ON pdm_prediction_history
    FOR SELECT TO authenticated USING (true);

-- Allow service role full access (used by the backend)
CREATE POLICY "Allow service role full access" ON pdm_prediction_history
    FOR ALL TO service_role USING (true) WITH CHECK (true);
