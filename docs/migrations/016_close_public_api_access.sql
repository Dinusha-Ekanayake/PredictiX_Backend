-- 016_close_public_api_access.sql
--
-- Close the database to the public anon key.
--
-- Why: the frontend bundle ships the Supabase anon key, which anyone can read.
-- Supabase grants anon and authenticated full rights on every new public table
-- (default privileges), and several tables carried "USING (true)" policies.
-- Probed with that key before this migration:
--   * tickets:            every row readable; update and delete permitted
--   * faqs:               insert permitted (feeds the chatbot's retrieval)
--   * knowledge_base:     every row readable
--   * ticket-attachments: objects listable; upload, overwrite and delete permitted
--   * SECURITY DEFINER functions (log_api_request, is_admin, handle_new_user)
--     callable over /rest/v1/rpc
--
-- After: PredictiX has no browser access to the database at all. The browser
-- calls the API, which uses its own connection (DATABASE_URL) or the
-- service-role key. anon and authenticated keep no table, sequence or function
-- rights, and new objects no longer receive them by default.
--
-- PREREQUISITE (otherwise production breaks): deploy a backend that uses
-- SUPABASE_SERVICE_ROLE_KEY and a frontend that uploads attachments through
-- the API, before applying this. Verify afterwards with
--   python scripts/security/check_public_access.py
--
-- Idempotent: REVOKE of an absent privilege, DROP POLICY IF EXISTS and the
-- bucket UPDATEs can all run again harmlessly.
--
-- Rollback (restores the exposure; only if something unforeseen depends on it):
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO anon, authenticated;
--   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
--     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO anon, authenticated;

BEGIN;

-- ── Tables, views and sequences ────────────────────────────────────────────
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;

-- ── Application functions (pgvector's extension functions are left alone) ──
-- Trigger functions keep working: PostgreSQL checks EXECUTE when a trigger is
-- created, not when it fires. The API runs as the owner, so it is unaffected.
REVOKE EXECUTE ON FUNCTION public.current_app_role()                   FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.generate_ticket_number()             FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user()                    FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.is_admin()                           FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.log_api_request()                    FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.match_knowledge(vector, integer)     FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.set_updated_at()                     FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.sync_report_warehouse()              FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.current_app_role(), public.generate_ticket_number(),
                           public.is_admin(), public.match_knowledge(vector, integer)
                           TO service_role;

-- ── Objects created from now on ────────────────────────────────────────────
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL     ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL     ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;

-- ── Policies that opened rows to everyone ──────────────────────────────────
-- Inert once the grants above are gone; dropped so that a future grant cannot
-- silently reopen the same rows.
DROP POLICY IF EXISTS tickets_select_authenticated            ON public.tickets;
DROP POLICY IF EXISTS tickets_insert_authenticated            ON public.tickets;
DROP POLICY IF EXISTS tickets_update_creator_assignee_or_admin ON public.tickets;
DROP POLICY IF EXISTS tickets_delete                          ON public.tickets;
DROP POLICY IF EXISTS "FAQs are viewable by everyone"         ON public.faqs;
DROP POLICY IF EXISTS insert_faqs                             ON public.faqs;
DROP POLICY IF EXISTS read_active_faqs                        ON public.faqs;
DROP POLICY IF EXISTS "Allow read access"                     ON public.knowledge_base;

-- ── Storage ────────────────────────────────────────────────────────────────
-- Uploads now go through the API with the service-role key, which bypasses
-- storage policies. With this policy gone, anonymous clients can no longer
-- list, upload, overwrite or delete attachments. Existing public URLs keep
-- working, because public buckets serve objects by URL without a policy.
DROP POLICY IF EXISTS "Allow Full Access to Attachments" ON storage.objects;

-- Size and type limits enforced by storage itself, matching the API's checks.
UPDATE storage.buckets
   SET file_size_limit = 10485760,
       allowed_mime_types = ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
 WHERE id IN ('ticket-attachments', 'asset-images');
UPDATE storage.buckets
   SET file_size_limit = 5242880,
       allowed_mime_types = ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
 WHERE id = 'avatars';
UPDATE storage.buckets
   SET file_size_limit = 26214400,
       allowed_mime_types = ARRAY['application/pdf']
 WHERE id = 'reports';

COMMIT;
