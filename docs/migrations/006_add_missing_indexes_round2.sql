-- Migration: Add indexes still missing after 004_add_missing_indexes.sql
-- Run this in Supabase SQL editor or via psql
--
-- 004 covered assets/tickets/maintenance_events/notifications. These five
-- tables were left with only a primary-key index despite being filtered by
-- asset_id/ticket_id/run_id on every asset-detail-panel load (assignments,
-- documents, status history tabs) or every prediction-explanation/
-- ticket-prediction lookup — each currently forces a sequential scan that's
-- invisible at today's seed-data scale but won't stay that way. Uses
-- CREATE INDEX CONCURRENTLY so this can run against the live DB without
-- locking the tables it indexes.

-- ── asset_assignments ───────────────────────────────────────────────────────
-- asset_id: every asset-detail "Assignments" tab load (asset_assignments.py
-- list_asset_assignments' non-admin path, and the admin path's join filter).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asset_assignments_asset_id
    ON asset_assignments (asset_id);

-- user_id: "assets assigned to me" lookups.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asset_assignments_user_id
    ON asset_assignments (user_id);

-- ── asset_documents ─────────────────────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asset_documents_asset_id
    ON asset_documents (asset_id);

-- ── asset_status_history ────────────────────────────────────────────────────
-- asset_id is now a required filter on every call to this endpoint (see
-- asset_status_history.py's list_asset_status_history — 400s without it),
-- so this table is scanned by asset_id on every single request it serves.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_asset_status_history_asset_id
    ON asset_status_history (asset_id);

-- ── prediction_explanations ─────────────────────────────────────────────────
-- run_id and asset_id are both real lookup keys for this table (see
-- prediction_explanations.py) — neither had an index.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prediction_explanations_run_id
    ON prediction_explanations (run_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_prediction_explanations_asset_id
    ON prediction_explanations (asset_id);

-- ── ticket_predictions ──────────────────────────────────────────────────────
-- ticket_id: predictions.py's get_ticket_prediction filters on this directly
-- (run_id already has a UNIQUE index from its own constraint).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ticket_predictions_ticket_id
    ON ticket_predictions (ticket_id);
