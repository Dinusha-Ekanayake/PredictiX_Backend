-- Migration: Add indexes for assets columns sortable via GET /assets (list_assets)
-- Run this in Supabase SQL editor or via psql
--
-- list_assets accepts sort_by=make|model|manufacture_year|current_mileage|
-- criticality_score|payload_capacity_kg (assets.py), each applying an
-- ORDER BY directly on the column. None of these had a backing index, so
-- every sorted list request forces a full sequential scan + sort of the
-- whole assets table — invisible at today's seed-data scale but won't stay
-- that way. Uses CREATE INDEX CONCURRENTLY so this can run against the live
-- DB without locking the table.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_make
    ON assets (make);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_model
    ON assets (model);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_manufacture_year
    ON assets (manufacture_year);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_current_mileage
    ON assets (current_mileage);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_criticality_score
    ON assets (criticality_score);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_payload_capacity_kg
    ON assets (payload_capacity_kg);
