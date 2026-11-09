-- Fullmark Research initial schema. Generated from app.db models.

CREATE TABLE fm_reviews (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(36) NOT NULL, 
	title TEXT NOT NULL, 
	protocol JSON NOT NULL, 
	protocol_hash VARCHAR(64) NOT NULL, 
	approved_at FLOAT, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_fm_reviews_owner_id ON fm_reviews (owner_id);

CREATE TABLE fm_articles (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	identity TEXT NOT NULL, 
	metadata_json JSON NOT NULL, 
	recommendation JSON NOT NULL, 
	pdf JSON NOT NULL, 
	extraction JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (review_id, identity), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id)
)

;
CREATE INDEX ix_fm_articles_review_id ON fm_articles (review_id);

CREATE TABLE fm_audit (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	actor TEXT NOT NULL, 
	action TEXT NOT NULL, 
	payload JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id)
)

;
CREATE INDEX ix_fm_audit_review_id ON fm_audit (review_id);

CREATE TABLE fm_jobs (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	request_key VARCHAR(100) NOT NULL, 
	payload JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	attempts INTEGER NOT NULL, 
	available_at FLOAT NOT NULL, 
	lease_until FLOAT NOT NULL, 
	external_id TEXT, 
	error TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (review_id, kind, request_key), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id)
)

;
CREATE INDEX ix_fm_jobs_available_at ON fm_jobs (available_at);
CREATE INDEX ix_fm_jobs_status ON fm_jobs (status);
CREATE INDEX ix_fm_jobs_review_id ON fm_jobs (review_id);

CREATE TABLE fm_searches (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	request_key VARCHAR(100) NOT NULL, 
	query TEXT NOT NULL, 
	max_records INTEGER NOT NULL, 
	total_found INTEGER NOT NULL, 
	translated_query TEXT NOT NULL, 
	raw JSON NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (review_id, request_key), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id)
)

;
CREATE INDEX ix_fm_searches_review_id ON fm_searches (review_id);

CREATE TABLE fm_decisions (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	article_id VARCHAR(36) NOT NULL, 
	actor VARCHAR(36) NOT NULL, 
	stage VARCHAR(30) NOT NULL, 
	verdict VARCHAR(20) NOT NULL, 
	reason TEXT NOT NULL, 
	created_at FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id), 
	FOREIGN KEY(article_id) REFERENCES fm_articles (id)
)

;
CREATE INDEX ix_fm_decisions_review_id ON fm_decisions (review_id);
CREATE INDEX ix_fm_decisions_article_id ON fm_decisions (article_id);

CREATE TABLE fm_records (
	id VARCHAR(36) NOT NULL, 
	review_id VARCHAR(36) NOT NULL, 
	search_id VARCHAR(36) NOT NULL, 
	article_id VARCHAR(36) NOT NULL, 
	source_id TEXT NOT NULL, 
	raw JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (search_id, source_id), 
	FOREIGN KEY(review_id) REFERENCES fm_reviews (id), 
	FOREIGN KEY(search_id) REFERENCES fm_searches (id), 
	FOREIGN KEY(article_id) REFERENCES fm_articles (id)
)

;
CREATE INDEX ix_fm_records_article_id ON fm_records (article_id);
CREATE INDEX ix_fm_records_review_id ON fm_records (review_id);
CREATE INDEX ix_fm_records_search_id ON fm_records (search_id);
ALTER TABLE public.fm_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_reviews FROM anon, authenticated;
GRANT SELECT ON public.fm_reviews TO authenticated;
CREATE POLICY fm_reviews_owner_read ON public.fm_reviews FOR SELECT TO authenticated USING (owner_id = (select auth.uid())::text);
ALTER TABLE public.fm_articles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_articles FROM anon, authenticated;
GRANT SELECT ON public.fm_articles TO authenticated;
CREATE POLICY fm_articles_owner_read ON public.fm_articles FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_articles.review_id AND r.owner_id = (select auth.uid())::text));
ALTER TABLE public.fm_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_audit FROM anon, authenticated;
GRANT SELECT ON public.fm_audit TO authenticated;
CREATE POLICY fm_audit_owner_read ON public.fm_audit FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_audit.review_id AND r.owner_id = (select auth.uid())::text));
ALTER TABLE public.fm_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_jobs FROM anon, authenticated;
GRANT SELECT ON public.fm_jobs TO authenticated;
CREATE POLICY fm_jobs_owner_read ON public.fm_jobs FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_jobs.review_id AND r.owner_id = (select auth.uid())::text));
ALTER TABLE public.fm_searches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_searches FROM anon, authenticated;
GRANT SELECT ON public.fm_searches TO authenticated;
CREATE POLICY fm_searches_owner_read ON public.fm_searches FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_searches.review_id AND r.owner_id = (select auth.uid())::text));
ALTER TABLE public.fm_decisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_decisions FROM anon, authenticated;
GRANT SELECT ON public.fm_decisions TO authenticated;
CREATE POLICY fm_decisions_owner_read ON public.fm_decisions FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_decisions.review_id AND r.owner_id = (select auth.uid())::text));
ALTER TABLE public.fm_records ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fm_records FROM anon, authenticated;
GRANT SELECT ON public.fm_records TO authenticated;
CREATE POLICY fm_records_owner_read ON public.fm_records FOR SELECT TO authenticated USING (EXISTS (SELECT 1 FROM public.fm_reviews r WHERE r.id = fm_records.review_id AND r.owner_id = (select auth.uid())::text));

CREATE FUNCTION public.fm_protect_audit() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN RAISE EXCEPTION 'Audit and decisions are append-only'; END;
$$;
REVOKE ALL ON FUNCTION public.fm_protect_audit() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER fm_audit_immutable BEFORE UPDATE OR DELETE ON public.fm_audit
FOR EACH ROW EXECUTE FUNCTION public.fm_protect_audit();
CREATE TRIGGER fm_decisions_immutable BEFORE UPDATE OR DELETE ON public.fm_decisions
FOR EACH ROW EXECUTE FUNCTION public.fm_protect_audit();
CREATE FUNCTION public.fm_protect_protocol() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
 IF NEW.owner_id <> OLD.owner_id OR NEW.protocol::text <> OLD.protocol::text OR NEW.protocol_hash <> OLD.protocol_hash OR (OLD.approved_at IS NOT NULL AND NEW.approved_at IS DISTINCT FROM OLD.approved_at) THEN
 RAISE EXCEPTION 'Protocol and ownership are immutable'; END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.fm_protect_protocol() FROM PUBLIC, anon, authenticated;
CREATE TRIGGER fm_protocol_immutable BEFORE UPDATE ON public.fm_reviews
FOR EACH ROW EXECUTE FUNCTION public.fm_protect_protocol();
INSERT INTO storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
VALUES ('fullmark-private','fullmark-private',false,20971520,ARRAY['application/pdf','application/json'])
ON CONFLICT (id) DO NOTHING;
CREATE POLICY fm_private_owner_read ON storage.objects FOR SELECT TO authenticated
USING (bucket_id = 'fullmark-private' AND (storage.foldername(name))[1] = (select auth.uid())::text);
