-- Drafts can evolve; approved protocols and ownership remain immutable.
CREATE OR REPLACE FUNCTION public.fm_protect_protocol() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
 IF NEW.owner_id <> OLD.owner_id OR
 (OLD.approved_at IS NOT NULL AND
 (NEW.protocol::text <> OLD.protocol::text OR NEW.protocol_hash <> OLD.protocol_hash OR
 NEW.approved_at IS DISTINCT FROM OLD.approved_at OR NEW.title <> OLD.title)) THEN
 RAISE EXCEPTION 'Approved protocol and ownership are immutable'; END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.fm_protect_protocol() FROM PUBLIC, anon, authenticated;
