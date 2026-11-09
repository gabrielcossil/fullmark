-- Internal migration metadata is deliberately unavailable to API clients.
-- Fresh installations create the tracking table through scripts/migrate.py first.
CREATE POLICY fm_migrations_deny_clients ON public.fm_schema_migrations
FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
