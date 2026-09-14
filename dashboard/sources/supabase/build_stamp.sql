-- When this snapshot was extracted.
--
-- The dashboard is a build-time parquet snapshot, so "is it updated?" has one
-- honest answer: the moment `evidence sources` ran against Supabase. now() is
-- evaluated by Postgres at extraction; rendered in UTC so the stamp reads the
-- same from any timezone. built_at is the raw timestamp for anything that wants
-- to compute with it.
--
-- ZERO-ROW SAFETY: a constant SELECT is always exactly one row.
select
  to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI "UTC"') as built_at_utc,
  (now() at time zone 'utc')::timestamp                        as built_at
