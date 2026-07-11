-- Migration: Add indexes for columns filtered/joined on nearly every request
-- Run this in Supabase SQL editor or via psql
--
-- None of these are auto-created by Postgres (only PKs and UNIQUE constraints
-- are). Every one of them is a WHERE/JOIN predicate hit on every admin
-- dashboard load, every asset list/detail fetch, and every user-scoped
-- profile/assets/tickets query — invisible at today's seed-data scale but a
-- sequential-scan risk as the fleet/ticket history grows. Uses
-- CREATE INDEX CONCURRENTLY so this can run against the live DB without
-- locking the tables it indexes.

-- ── assets ──────────────────────────────────────────────────────────────────
-- Note: idx_assets_warehouse (warehouse_id) and idx_assets_status (status)
-- already existed before this migration — not re-created here.

-- assigned_to: filtered on every "my assets" / user-scoped query
-- (profile.py get_my_assets/get_my_stats, user_profile.py equivalents).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_assigned_to
    ON assets (assigned_to);

-- Composite (warehouse_id, status): the two hottest combined filters for
-- the admin dashboard's health/risk aggregates and the assets list/count
-- endpoints' most common filter combination.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_warehouse_status
    ON assets (warehouse_id, status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_assets_health_band
    ON assets (health_band);

-- ── tickets ─────────────────────────────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tickets_warehouse_id
    ON tickets (warehouse_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tickets_created_by
    ON tickets (created_by);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tickets_assigned_to
    ON tickets (assigned_to);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tickets_status
    ON tickets (status);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tickets_created_at
    ON tickets (created_at DESC);

-- ── maintenance_events ─────────────────────────────────────────────────────
-- Note: idx_maintenance_events_asset (asset_id) already existed — not
-- re-created here.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_maintenance_events_performed_at
    ON maintenance_events (performed_at DESC);

-- ── notifications ───────────────────────────────────────────────────────────
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_user_id
    ON notifications (user_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_created_at
    ON notifications (created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_notifications_related_asset_id
    ON notifications (related_asset_id);
