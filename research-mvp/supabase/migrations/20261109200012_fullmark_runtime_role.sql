-- A dedicated backend role; no account password is stored in migrations.
CREATE ROLE fullmark_runtime NOLOGIN NOINHERIT NOBYPASSRLS CONNECTION LIMIT 8;
GRANT USAGE ON SCHEMA public TO fullmark_runtime;
GRANT SELECT, INSERT, UPDATE ON public.fm_reviews, public.fm_searches, public.fm_articles, public.fm_records, public.fm_jobs TO fullmark_runtime;
GRANT SELECT, INSERT ON public.fm_decisions, public.fm_audit TO fullmark_runtime;
CREATE POLICY fm_reviews_runtime ON public.fm_reviews FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_searches_runtime ON public.fm_searches FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_articles_runtime ON public.fm_articles FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_records_runtime ON public.fm_records FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_jobs_runtime ON public.fm_jobs FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_decisions_runtime ON public.fm_decisions FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
CREATE POLICY fm_audit_runtime ON public.fm_audit FOR ALL TO fullmark_runtime USING (true) WITH CHECK (true);
ALTER ROLE fullmark_runtime SET statement_timeout = '120s';
ALTER ROLE fullmark_runtime SET idle_in_transaction_session_timeout = '60s';
