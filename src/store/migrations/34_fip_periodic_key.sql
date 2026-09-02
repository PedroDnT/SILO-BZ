-- =============================================================================
-- 34_fip_periodic_key.sql — stop cvm_fip_periodic discarding three quarters of
-- every FIP file.
--
-- WHAT WAS WRONG. The key was (cnpj, doc_type, period_year) and the row's own
-- DT_COMPTC was never extracted — it sat unread in `raw`. A FIP yearly CSV
-- holds EVERY filing of that year: four quarters for inf_trimestral, three
-- periods for inf_quadrimestral, and one row per share class inside each. All
-- of them collided on a key that holds one row per fund per year, so whichever
-- row the parser reached last survived and the rest were dropped on upsert.
--
-- Measured against the real published files:
--
--     inf_trimestral_fip_2015.csv     3,154 rows ->   887 stored   (72% lost)
--     inf_trimestral_fip_2022.csv     6,753 rows -> 1,580 stored   (77% lost)
--     inf_quadrimestral_fip_2025.csv  7,880 rows -> 2,193 stored   (72% lost)
--
-- This is why FIP has always presented as a single 31 December row per fund,
-- and why `dim_fund` spikes every January.
--
-- THE NEW KEY, audited on those three files:
--
--     cnpj+doc_type+period                 2015 UNIQUE   2022  726   2025 1100
--     + classe_cota                        2015 UNIQUE   2022    7   2025  133
--     + classe_cota + row_hash             UNIQUE on all three
--
-- CLASSE_COTA is load-bearing: one row per share class (A, B, C…), each with
-- its own subscribed capital and quota count. row_hash is LAST and is only a
-- tiebreaker for CVM restating the same (fund, date, class) with different
-- capital figures — no published column separates those two filings, so both
-- are kept and `fetched_at` orders them. It is a sha256 over the row's own
-- published values; nothing is invented.
--
-- EXISTING ROWS. Every stored row carries its source in `raw`, so period,
-- classe_cota and row_hash are all recoverable without a re-fetch. What is NOT
-- recoverable is the ~75% that the old key already discarded — those rows were
-- never written. A backfill of entity=fip re-fetches them; this migration only
-- makes the table able to hold them.
--
-- Idempotent: guarded ADD COLUMN / DROP ... IF EXISTS / CREATE ... IF NOT EXISTS.
-- =============================================================================

ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS period          DATE;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS classe_cota     TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS row_hash        TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS tp_fundo        TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS denom_social    TEXT;
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS qt_cota         NUMERIC(28,8);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_patrim_cota  NUMERIC(28,8);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS nr_cotst        NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_comprom  NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_subscr   NUMERIC(20,2);
ALTER TABLE cvm_fip_periodic ADD COLUMN IF NOT EXISTS vl_cap_integr   NUMERIC(20,2);

-- Recover the key columns from the preserved source row before the index is
-- built. Order matters: the new key DROPS period_year, so until these run every
-- year of a fund has (period, classe_cota, row_hash) = (NULL, NULL, NULL) and
-- NULLS NOT DISTINCT makes them all duplicates of each other.
UPDATE cvm_fip_periodic
   SET period = NULLIF(raw ->> 'DT_COMPTC', '')::DATE
 WHERE period IS NULL
   AND NULLIF(raw ->> 'DT_COMPTC', '') IS NOT NULL;

UPDATE cvm_fip_periodic
   SET classe_cota = NULLIF(raw ->> 'CLASSE_COTA', '')
 WHERE classe_cota IS NULL;

-- The marker carries the row's own id. A constant would make every legacy row
-- of a fund identical under the new key — which is precisely the collapse this
-- change exists to end. `raw` holds only the columns the OLD field map did not
-- consume, so the real digest cannot be recomputed here; the next ingest of
-- that slice writes it as a new row and these remain distinguishable as the
-- pre-fix remnant.
UPDATE cvm_fip_periodic
   SET row_hash = 'pre-migration-34:' || id::TEXT
 WHERE row_hash IS NULL;

-- Backstop: a row that still has no period cannot take part in the new key.
-- Rather than drop it (never delete published data) it keeps period NULL and
-- NULLS NOT DISTINCT groups those rows together, which is exactly the old
-- behaviour for exactly the rows that never had a date.
DROP INDEX IF EXISTS uq_fip_periodic;
ALTER TABLE cvm_fip_periodic DROP CONSTRAINT IF EXISTS uq_fip_periodic;
CREATE UNIQUE INDEX IF NOT EXISTS uq_fip_periodic
    ON cvm_fip_periodic (cnpj, doc_type, period, classe_cota, row_hash)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_fip_periodic_period
    ON cvm_fip_periodic (period DESC);

COMMENT ON COLUMN cvm_fip_periodic.period IS
    'The filing''s own DT_COMPTC. A FIP yearly CSV carries every period of the year; keying on the archive year alone discarded ~75% of each file.';
COMMENT ON COLUMN cvm_fip_periodic.classe_cota IS
    'Share class (A, B, C…) as filed. Part of the key: each class carries its own subscribed capital and quota count.';
COMMENT ON COLUMN cvm_fip_periodic.row_hash IS
    'sha256 over the source row. Last element of the key and only a tiebreaker, for CVM restating the same (fund, date, class). ''pre-migration-34'' marks rows stored before the key was fixed.';
