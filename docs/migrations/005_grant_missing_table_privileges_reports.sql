-- Migration: Grant missing table privileges for departments, maintenance_events,
--            asset_failure_predictions, asset_cost_predictions
-- Run this in Supabase SQL editor or via psql
--
-- Same root cause as the earlier profiles/notifications/sensor_readings/
-- warehouses fix: tables created via SQLAlchemy/Alembic migrations don't
-- automatically receive the GRANTs Supabase's own dashboard/SQL editor adds
-- by default. RLS policies alone do NOT grant table access — Postgres
-- requires the base GRANT independently of RLS.
--
-- Discovered while fixing the asset-report PDF crash: AssetContextBuilder
-- (app/services/context_builder.py) queries these 4 tables through the
-- Supabase REST client (not the backend's direct-Postgres SQLAlchemy path),
-- and was silently getting `permission denied` on all four — caught and
-- logged as a warning, degrading every real asset report to missing
-- maintenance history, failure predictions, and cost estimates, with no
-- visible error to the user. Verified live against production data
-- (2026-08-07) before this migration.
--
-- Confirmed before this migration:
--   departments                 — RLS disabled, no policies, no grants
--   maintenance_events          — RLS enabled, has policies, NO grants
--   asset_failure_predictions   — RLS enabled, has policies, NO grants
--   asset_cost_predictions      — RLS enabled, has policies, NO grants

-- ─── maintenance_events ──────────────────────────────────────────────────────
-- Existing policies already correctly scope this (select: any authenticated
-- user; insert/update: is_admin() only) — this migration only opens the base
-- table gate the policies act on top of, per row.
GRANT SELECT, INSERT, UPDATE ON TABLE public.maintenance_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.maintenance_events TO service_role;

-- ─── asset_failure_predictions ────────────────────────────────────────────────
-- Existing policy is read-only for authenticated (no insert/update policy
-- exists — these rows are written exclusively by the backend's batch
-- prediction job via SQLAlchemy, not through PostgREST).
GRANT SELECT ON TABLE public.asset_failure_predictions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.asset_failure_predictions TO service_role;

-- ─── asset_cost_predictions ────────────────────────────────────────────────────
GRANT SELECT ON TABLE public.asset_cost_predictions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.asset_cost_predictions TO service_role;

-- ─── departments ────────────────────────────────────────────────────────────
-- Same gap warehouses had before the earlier migration: no RLS at all.
-- Every authenticated user needs to read department names (asset detail
-- pages, report generation); writes stay admin-only, matching
-- app/routers/departments.py's existing app-level enforcement.
ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "departments_select_authenticated" ON public.departments
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "departments_write_admin" ON public.departments
    FOR INSERT TO authenticated WITH CHECK (is_admin());

CREATE POLICY "departments_update_admin" ON public.departments
    FOR UPDATE TO authenticated USING (is_admin()) WITH CHECK (is_admin());

CREATE POLICY "departments_delete_admin" ON public.departments
    FOR DELETE TO authenticated USING (is_admin());

GRANT SELECT ON TABLE public.departments TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.departments TO service_role;

-- ─── Verification queries (run manually after applying, not part of the migration) ───
-- SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
--   WHERE table_name IN ('departments', 'maintenance_events', 'asset_failure_predictions', 'asset_cost_predictions')
--   AND grantee IN ('anon', 'authenticated', 'service_role')
--   ORDER BY table_name, grantee;
--
-- SELECT relname, relrowsecurity FROM pg_class
--   WHERE relname IN ('departments', 'maintenance_events', 'asset_failure_predictions', 'asset_cost_predictions');
