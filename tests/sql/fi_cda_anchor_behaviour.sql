-- Executed check for the /fi CDA anchor (#476). Regex tests pin the SQL text;
-- this runs the two real dashboard sources over rows. A temp cvm_fi_cda shadows
-- the landing table (pg_temp comes first for relations), inside a transaction
-- that is rolled back, so it runs on any database with latest_complete_period()
-- (CI's sql-compile job, or a scratch copy). Run from the repo root:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/fi_cda_anchor_behaviour.sql

BEGIN;

\set fi_alloc `cat dashboard/sources/supabase/fi_allocation.sql`
\set fi_top `cat dashboard/sources/supabase/fi_top_aplic.sql`

-- The FI cap is pinned here. Earlier CI steps seed fi facts in 2024-12, so the
-- real latest_complete_period('fi') would cap both sources there and the test
-- would depend on what those steps seeded. In production the FI cap (2026-08)
-- is LATER than the last complete CDA month (2026-05); this reproduces that.
-- A function in pg_temp is never found by an unqualified call, so the real one
-- is replaced for this transaction; the ROLLBACK at the end restores it.
CREATE OR REPLACE FUNCTION public.latest_complete_period(p_entity_type TEXT DEFAULT NULL)
RETURNS date LANGUAGE sql STABLE AS $f$
  SELECT (date_trunc('month', current_date) - interval '2 months')::date
$f$;

CREATE TEMP TABLE cvm_fi_cda (
  period date, cnpj text, tp_aplic text, tp_ativo text, vl_merc_pos_final numeric
);

-- 21 months ending two months ago. The first 18 hold 120 funds; the last three
-- are filed thin (74, 72, 72), the shape of 2026-06 to 2026-08 in issue #476.
INSERT INTO cvm_fi_cda
SELECT m::date, 'F' || lpad(i::text, 5, '0'), 'Títulos Públicos', 'Título público federal', 1000 + i
FROM generate_series(date_trunc('month', current_date) - interval '22 months',
                     date_trunc('month', current_date) - interval '2 months',
                     interval '1 month') m,
     LATERAL (SELECT CASE
                WHEN m = date_trunc('month', current_date) - interval '4 months' THEN 74
                WHEN m >= date_trunc('month', current_date) - interval '3 months' THEN 72
                ELSE 120 END AS n) c,
     generate_series(1, c.n) i;

CREATE TEMP TABLE r_alloc AS :fi_alloc;
CREATE TEMP TABLE r_top AS :fi_top;

DO $$
DECLARE
  want date := (date_trunc('month', current_date) - interval '5 months')::date;
  got date;
  n int;
BEGIN
  SELECT max(period) INTO got FROM r_alloc;
  IF got IS DISTINCT FROM want THEN
    RAISE EXCEPTION 'fi_allocation ends at %, want % (last complete CDA month)', got, want;
  END IF;
  SELECT period, n_funds INTO got, n FROM r_top LIMIT 1;
  IF got IS DISTINCT FROM want OR n <> 120 THEN
    RAISE EXCEPTION 'fi_top_aplic at % with % funds, want % with 120', got, n, want;
  END IF;
END $$;

-- CVM completes the first thin month: the anchor moves up by itself, and the
-- two months still thin stay out.
INSERT INTO cvm_fi_cda
SELECT date_trunc('month', current_date) - interval '4 months',
       'F' || lpad(i::text, 5, '0'), 'Títulos Públicos', 'Título público federal', 1000 + i
FROM generate_series(75, 120) i;

DROP TABLE r_alloc, r_top;
CREATE TEMP TABLE r_alloc AS :fi_alloc;
CREATE TEMP TABLE r_top AS :fi_top;

DO $$
DECLARE
  want date := (date_trunc('month', current_date) - interval '4 months')::date;
  got date;
BEGIN
  SELECT max(period) INTO got FROM r_alloc;
  IF got IS DISTINCT FROM want THEN
    RAISE EXCEPTION 'after the month completes, fi_allocation ends at %, want %', got, want;
  END IF;
  SELECT period INTO got FROM r_top LIMIT 1;
  IF got IS DISTINCT FROM want THEN
    RAISE EXCEPTION 'after the month completes, fi_top_aplic is at %, want %', got, want;
  END IF;
END $$;

-- An empty table keeps both sources emitting their safety row.
TRUNCATE cvm_fi_cda;
DROP TABLE r_alloc, r_top;
CREATE TEMP TABLE r_alloc AS :fi_alloc;
CREATE TEMP TABLE r_top AS :fi_top;
DO $$
BEGIN
  IF (SELECT count(*) FROM r_top) <> 1 OR (SELECT count(*) FROM r_alloc) = 0 THEN
    RAISE EXCEPTION 'an empty cvm_fi_cda must still yield rows (zero-row safety)';
  END IF;
END $$;

DO $$ BEGIN RAISE NOTICE '/fi CDA anchor OK'; END $$;
ROLLBACK;
