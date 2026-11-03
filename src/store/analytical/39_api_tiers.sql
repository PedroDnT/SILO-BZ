-- =============================================================================
-- 39_api_tiers.sql
-- api.my_tier() and api.rate_hit(p_bucket): the API v2 gateway's tier and its
-- requests-per-minute count, kept in Postgres (catalog v82, #1064; owner
-- decisions 2026-11-03, #1061).
--
-- The gateway (supabase/functions/silo-api) calls both through PostgREST with
-- the caller's own token, so auth.uid() is the caller's:
--   my_tier()   'pro' when auth.uid() has a row in public.api_user_tier,
--               'signed_in' when auth.uid() is set, else 'anonymous'. A Supabase
--               anonymous sign-in (claim is_anonymous = true) is 'anonymous':
--               it proves no identity.
--   rate_hit()  adds one hit to the current minute of the caller's bucket and
--               returns the new count. A signed-in caller's bucket is always
--               'u:<auth.uid()>': p_bucket is ignored, so no user can charge
--               another user's bucket. An anonymous caller's bucket is p_bucket,
--               which must be 'ip:<address>' (22023 otherwise). Then it deletes
--               at most 100 rows older than one hour, by minute (an index range,
--               never a table-wide delete), skipping rows another call holds.
-- The limits themselves are the gateway's (config.ts TIERS); SQL only counts.
--
-- These two are plumbing for the gateway, not data: they are published in
-- openapi.json (anything granted to anon is reachable on PostgREST), but not as
-- MCP tools (serve/endpoint_manifest.py GATEWAY_ONLY).
--
-- HONEST LIMIT. Anyone holding the publishable key can call rate_hit with any
-- ip: bucket, and the v1 PostgREST paths bypass the gateway entirely (#1065).
-- The limit protects the v2 surface from ordinary overuse, not from an attacker.
--
-- PRIVILEGES. SECURITY DEFINER with an empty pinned search_path, every relation
-- schema-qualified. EXECUTE revoked from PUBLIC, granted to anon and
-- authenticated only: not to silo_api, whose transactions are read-only and
-- which never calls the gateway. The tables (migration 84) have no client grant.
--
-- auth.uid() exists on Supabase only. A plpgsql body is not resolved when it is
-- created, so this file applies on a plain Postgres (the CI SQL compile) too;
-- calling either function there fails, which is correct: there is no caller.
-- =============================================================================

BEGIN;

DO $guard$
BEGIN
    IF to_regclass('public.api_user_tier') IS NULL
       OR to_regclass('public.api_rate_counter') IS NULL THEN
        RAISE EXCEPTION '39_api_tiers.sql needs public.api_user_tier and public.api_rate_counter (migration 84); apply the schema first';
    END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION api.my_tier()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_uid    UUID := auth.uid();
    v_claims TEXT := current_setting('request.jwt.claims', true);
BEGIN
    IF v_uid IS NULL THEN
        RETURN 'anonymous';
    END IF;
    BEGIN
        IF COALESCE((NULLIF(btrim(v_claims), '')::jsonb ->> 'is_anonymous')::boolean, FALSE) THEN
            RETURN 'anonymous';
        END IF;
    EXCEPTION WHEN others THEN
        -- Unparseable claims are a reason not to trust them, never a raise.
        RETURN 'anonymous';
    END;
    IF EXISTS (SELECT 1 FROM public.api_user_tier t WHERE t.user_id = v_uid AND t.tier = 'pro') THEN
        RETURN 'pro';
    END IF;
    RETURN 'signed_in';
END;
$fn$;

COMMENT ON FUNCTION api.my_tier() IS
    'The caller''s API v2 tier: pro when the signed-in user has a row in the private api_user_tier table, signed_in for any other signed-in user, anonymous otherwise (no token, the publishable key, or a Supabase anonymous sign-in). The v2 gateway calls it once per token and applies that tier''s limits (supabase/functions/silo-api/config.ts). Gateway plumbing: not an MCP tool. Returns one value, never a row set.';

REVOKE ALL ON FUNCTION api.my_tier() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.my_tier() TO anon, authenticated;

CREATE OR REPLACE FUNCTION api.rate_hit(p_bucket TEXT DEFAULT NULL)
RETURNS INTEGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $fn$
DECLARE
    v_minute TIMESTAMPTZ := date_trunc('minute', now());
    v_bucket TEXT;
    v_hits   INTEGER;
BEGIN
    IF api.my_tier() <> 'anonymous' THEN
        v_bucket := 'u:' || auth.uid()::text;
    ELSE
        v_bucket := btrim(p_bucket);
        IF v_bucket IS NULL OR v_bucket !~ '^ip:[0-9A-Fa-f:.]{2,45}$' THEN
            RAISE EXCEPTION 'rate_hit: an anonymous caller''s bucket is ip:<address> (IPv4 or IPv6); got %',
                COALESCE(quote_literal(p_bucket), 'null')
                USING ERRCODE = '22023';
        END IF;
    END IF;

    INSERT INTO public.api_rate_counter AS c (bucket, minute, hits)
    VALUES (v_bucket, v_minute, 1)
    ON CONFLICT ON CONSTRAINT uq_api_rate_counter
    DO UPDATE SET hits = c.hits + 1
    RETURNING c.hits INTO v_hits;

    -- Bounded cleanup: at most 100 rows older than one hour, found through
    -- idx_api_rate_counter_minute. Never a table-wide delete.
    DELETE FROM public.api_rate_counter d
     WHERE d.ctid IN (
           SELECT o.ctid
             FROM public.api_rate_counter o
            WHERE o.minute < v_minute - INTERVAL '1 hour'
            LIMIT 100
              FOR UPDATE SKIP LOCKED);

    RETURN v_hits;
END;
$fn$;

COMMENT ON FUNCTION api.rate_hit(TEXT) IS
    'Counts one API v2 request in the current minute and returns the bucket''s hits so far this minute. A signed-in caller''s bucket is u:<user id> and p_bucket is ignored, so no user can charge another''s; an anonymous caller''s bucket is p_bucket, which must be ip:<address> (22023 otherwise). Deletes at most 100 rows older than one hour on each call. The v2 gateway compares the count with the tier''s requests per minute and answers 429 above it. Gateway plumbing: not an MCP tool. It writes a counter row and nothing else.';

REVOKE ALL ON FUNCTION api.rate_hit(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.rate_hit(TEXT) TO anon, authenticated;

COMMIT;
