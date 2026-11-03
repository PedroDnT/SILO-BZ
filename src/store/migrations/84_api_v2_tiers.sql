-- API v2 tiers and the per-minute rate limit, #1064 (owner decisions 2026-11-03, #1061).
-- Two private tables behind api.my_tier() and api.rate_hit() (39_api_tiers.sql).
-- api_user_tier: the callers above signed_in, one row per Supabase Auth user. The
-- owner inserts rows by hand (no write path from any API); 'pro' is the only tier.
-- api_rate_counter: one row per bucket and minute. bucket is 'u:<user id>' for a
-- signed-in caller and 'ip:<address>' for an anonymous one. api.rate_hit() deletes
-- rows older than one hour itself, a bounded delete on minute.
-- No grant to anon, authenticated or silo_api: only the SECURITY DEFINER functions
-- read or write them. RLS on with no policy, so the Data API sees nothing either.
-- The foreign key to auth.users is added only where the auth schema exists
-- (Supabase); a plain Postgres (the CI SQL compile) has none and gets the table
-- without it.
BEGIN;
CREATE TABLE IF NOT EXISTS api_user_tier (
    user_id    UUID        NOT NULL,
    tier       TEXT        NOT NULL CHECK (tier IN ('pro')),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note       TEXT,
    CONSTRAINT uq_api_user_tier UNIQUE (user_id)
);
CREATE TABLE IF NOT EXISTS api_rate_counter (
    bucket TEXT        NOT NULL CHECK (bucket ~ '^(u|ip):' AND length(bucket) <= 80),
    minute TIMESTAMPTZ NOT NULL CHECK (minute = date_trunc('minute', minute)),
    hits   INTEGER     NOT NULL DEFAULT 1 CHECK (hits >= 0),
    CONSTRAINT uq_api_rate_counter UNIQUE (bucket, minute)
);
CREATE INDEX IF NOT EXISTS idx_api_rate_counter_minute ON api_rate_counter (minute);
COMMENT ON TABLE api_user_tier IS
    'API v2 tiers above signed_in (#1064): one row per Supabase Auth user, tier pro only. Rows are inserted by the owner by hand; no API writes here. Read by api.my_tier() (SECURITY DEFINER). Private: no client grant.';
COMMENT ON TABLE api_rate_counter IS
    'API v2 requests per minute (#1064): hits per bucket (u:<user id> signed in, ip:<address> anonymous) and minute, written by api.rate_hit() (SECURITY DEFINER), which deletes rows older than one hour in bounded batches. Private: no client grant.';
DO $fk$
BEGIN
    IF to_regclass('auth.users') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint
                        WHERE conname = 'fk_api_user_tier_user'
                          AND conrelid = 'public.api_user_tier'::regclass) THEN
        ALTER TABLE api_user_tier
            ADD CONSTRAINT fk_api_user_tier_user
            FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END
$fk$;
ALTER TABLE api_user_tier ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_rate_counter ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON api_user_tier, api_rate_counter FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON api_user_tier, api_rate_counter FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;
COMMIT;
