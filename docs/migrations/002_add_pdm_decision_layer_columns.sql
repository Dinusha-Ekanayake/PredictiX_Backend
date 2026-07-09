-- Migration: Add v7 model auditability + decision-layer columns to pdm_batch_predictions
-- Run this in Supabase SQL editor or via psql

ALTER TABLE pdm_batch_predictions
    -- Auditability: which model generation + exact input produced this row,
    -- so predictions can later be joined against maintenance_events to
    -- measure real precision/recall and know when to retrain.
    ADD COLUMN IF NOT EXISTS model_version      TEXT,
    ADD COLUMN IF NOT EXISTS feature_snapshot   JSONB DEFAULT '{}'::jsonb,

    -- Decision layer (app.ai.services.pdm_decision_service.build_decision) —
    -- reconciles classifier + regressor + health score into one tiered
    -- recommendation instead of three independently-speaking numbers.
    ADD COLUMN IF NOT EXISTS tier               TEXT,
    ADD COLUMN IF NOT EXISTS agreement          BOOLEAN,
    ADD COLUMN IF NOT EXISTS display_mode       TEXT,
    ADD COLUMN IF NOT EXISTS horizon_text       TEXT,
    ADD COLUMN IF NOT EXISTS recommended_action TEXT,
    ADD COLUMN IF NOT EXISTS horizon_saturated  BOOLEAN DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_pdm_batch_predictions_tier
    ON pdm_batch_predictions (tier);
