-- 43 — keep every CVM version of FII filings
--
-- WHY. CVM's FII files (inf_mensal geral / complemento / ativo_passivo, and the
-- INF_TRIMESTRAL / INF_ANUAL / DFIN members behind cvm_fii_periodic) carry a
-- `Versao` column: a filer that corrects a monthly or quarterly report
-- re-submits it and CVM bumps the version. Our keys left it out —
-- cvm_fii_mensal on (cnpj, period, doc_subtype), cvm_fii_periodic on
-- (cnpj, doc_type, period_year, data_referencia) — so ON CONFLICT DO UPDATE
-- overwrote the original with the restatement and "what did the fund first
-- declare" was lost at write time (COMPETITIVE_GAPS.md §4.3, backlog B4).
-- Owner decision 2026-09-24: keep every version.
--
-- WHAT THIS DOES
--   1. cvm_fii_mensal gains a typed `versao INT` (cvm_fii_periodic has had one
--      since migration 15, populated only for the trimestral_* members).
--   2. Both unique keys gain `versao`, NULLS NOT DISTINCT.
--   3. `versao` is backfilled from `raw` ->> 'Versao' (the CSV header is
--      exactly `Versao` and the mensal maps never consumed it, so it sat in the
--      residual). The key is then removed from `raw`, which only ever holds
--      fields no typed column models.
--   4. vw_fii_mensal_latest / vw_fii_periodic_latest: ONE row per former key,
--      the highest version. Every existing reader is repointed to them, so no
--      downstream number changes meaning.
--   5. instrument_activity (migration 07) is re-created reading the latest view
--      so its FII n_obs stays one per (fund, month, subtype).
--
-- WHY THE UPGRADE CANNOT COLLIDE. Every existing row is the one version the
-- old key let survive, so (cnpj, period, doc_subtype) is already unique, and
-- adding a column to a unique key only makes collisions rarer. Rows whose raw
-- has no usable Versao keep versao NULL, and NULLS NOT DISTINCT makes those
-- dedupe exactly as they did under the old key.
--
-- WHAT IT CANNOT DO. History ingested before this migration holds only the
-- version CVM was shipping when we last fetched it — the earlier versions were
-- overwritten and are not recoverable from our copy. CVM's yearly files carry
-- whatever versions CVM still publishes, and a re-ingest (run_backfill --entity fii)
-- keeps any version those files contain from now on.
--
-- WHY THE VIEWS LIVE HERE AND NOT IN analytical/. instrument_activity is a
-- migration-layer view (07) that reads cvm_fii_mensal, and migrations run
-- before the analytical layer, so the latest-version view has to exist at this
-- layer. It is NOT mirrored in schema.sql: on a fresh database migration 01
-- retypes cvm_fii_mensal numeric columns after schema.sql, and a view over
-- m.* would block that ALTER COLUMN TYPE.
--
-- Idempotent and psql -v ON_ERROR_STOP=1 clean: ADD COLUMN IF NOT EXISTS, the
-- key swaps are catalog-guarded (a no-op once the key names versao), the
-- backfill is guarded by a marker in the column comment (so the daily re-apply
-- does not scan the table), and the views are CREATE OR REPLACE.
-- No semicolons in comments.

ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS versao INT;

ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS versao INT;

-- ---------------------------------------------------------------------------
-- 2. The keys. Same constraint names, so upsert_rows' ON CONFLICT column list
--    (src/parsers/field_maps/fii_*.py CONFLICT) resolves to them.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_fii_mensal'::regclass
          AND conname  = 'uq_fii_mensal'
          AND pg_get_constraintdef(oid) ILIKE '%versao%'
    ) THEN
        ALTER TABLE cvm_fii_mensal DROP CONSTRAINT IF EXISTS uq_fii_mensal;
        ALTER TABLE cvm_fii_mensal ADD CONSTRAINT uq_fii_mensal
            UNIQUE NULLS NOT DISTINCT (cnpj, period, doc_subtype, versao);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_fii_periodic'::regclass
          AND conname  = 'uq_fii_periodic'
          AND pg_get_constraintdef(oid) ILIKE '%versao%'
    ) THEN
        ALTER TABLE cvm_fii_periodic DROP CONSTRAINT IF EXISTS uq_fii_periodic;
        ALTER TABLE cvm_fii_periodic ADD CONSTRAINT uq_fii_periodic
            UNIQUE NULLS NOT DISTINCT (cnpj, doc_type, period_year, data_referencia, versao);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. Backfill versao from raw, once per table. The marker is the column
--    comment set right after each DO block: once it says "migration 43" the
--    block is skipped, so the daily re-apply does not scan the table.
--    A Versao that is not a plain integer >= 1 is left in raw and versao stays
--    NULL — the same rule ingest applies (src/parsers/validation.parse_versao).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF COALESCE(col_description('cvm_fii_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fii_mensal'::regclass AND attname = 'versao')),
           '') NOT LIKE '%migration 43%' THEN
        UPDATE cvm_fii_mensal
           SET versao = btrim(raw ->> 'Versao')::int,
               raw    = raw - 'Versao'
         WHERE versao IS NULL
           AND CASE WHEN raw ->> 'Versao' ~ '^\s*[0-9]{1,9}\s*$'
                    THEN btrim(raw ->> 'Versao')::int >= 1
                    ELSE false END;
    END IF;
END $$;

COMMENT ON COLUMN cvm_fii_mensal.versao IS
  'CVM Versao of the filing (migration 43). Part of uq_fii_mensal, so every restatement is its own row. NULL only where the source row carried no usable Versao. Read one row per (cnpj, period, doc_subtype) through vw_fii_mensal_latest.';

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fii_periodic'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fii_periodic'::regclass AND attname = 'versao')),
           '') NOT LIKE '%migration 43%' THEN
        UPDATE cvm_fii_periodic
           SET versao = btrim(raw ->> 'Versao')::int,
               raw    = raw - 'Versao'
         WHERE versao IS NULL
           AND CASE WHEN raw ->> 'Versao' ~ '^\s*[0-9]{1,9}\s*$'
                    THEN btrim(raw ->> 'Versao')::int >= 1
                    ELSE false END;
    END IF;
END $$;

COMMENT ON COLUMN cvm_fii_periodic.versao IS
  'CVM Versao of the filing (migration 43). Part of uq_fii_periodic, so every restatement is its own row. NULL only where the source row carried no usable Versao. Read one row per (cnpj, doc_type, period_year, data_referencia) through vw_fii_periodic_latest.';

-- ---------------------------------------------------------------------------
-- 4. One row per former key — the latest version.
--
--    DISTINCT ON the OLD key, highest versao first. NULLS LAST: a row with a
--    published version outranks a legacy row that carried none. fetched_at and
--    id break any remaining tie deterministically (newest write wins, which is
--    what the old overwrite did).
--
--    Before any restatement lands, every former key has exactly one row, so
--    these views return the table unchanged — that is why repointing a reader
--    is provably equivalent today and stays "the latest version" afterwards.
--
--    security_invoker: the views read with the caller's privileges, so they
--    can never become a door around the landing-table revokes in
--    analytical/12_grants_and_rls.sql (which also sweeps the vw_ prefix).
--    DISTINCT ON columns are exactly the old key, so a WHERE on cnpj / period /
--    doc_subtype is pushed below the DISTINCT ON by the planner.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_fii_mensal_latest
WITH (security_invoker = true) AS
SELECT DISTINCT ON (m.cnpj, m.period, m.doc_subtype) m.*
FROM cvm_fii_mensal m
ORDER BY m.cnpj, m.period, m.doc_subtype,
         m.versao DESC NULLS LAST, m.fetched_at DESC, m.id DESC;

COMMENT ON VIEW vw_fii_mensal_latest IS
  'cvm_fii_mensal at its pre-migration-43 grain: one row per (cnpj, period, doc_subtype), the highest CVM versao. Every analytical object and dashboard source that reads FII monthly data reads this, never the table.';

CREATE OR REPLACE VIEW vw_fii_periodic_latest
WITH (security_invoker = true) AS
SELECT DISTINCT ON (p.cnpj, p.doc_type, p.period_year, p.data_referencia) p.*
FROM cvm_fii_periodic p
ORDER BY p.cnpj, p.doc_type, p.period_year, p.data_referencia,
         p.versao DESC NULLS LAST, p.fetched_at DESC, p.id DESC;

COMMENT ON VIEW vw_fii_periodic_latest IS
  'cvm_fii_periodic at its pre-migration-43 grain: one row per (cnpj, doc_type, period_year, data_referencia), the highest CVM versao.';

-- Close the window between this migration and the analytical apply: Supabase's
-- default privileges grant new public objects to anon/authenticated.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON vw_fii_mensal_latest, vw_fii_periodic_latest FROM anon, authenticated';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 5. instrument_activity (migration 07) — identical except that the FII arm
--    reads the latest view, so n_obs keeps counting one row per
--    (fund, month, subtype) once restatements are stored. first/last_period
--    are unchanged either way. Migration 07 re-creates the old definition on
--    every apply and this file, applied after it, restores this one.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW instrument_activity AS
WITH activity AS (
    SELECT 'fi'::text AS entity_type, cnpj, 'daily'::text AS granularity,
           MIN(dt_comptc) AS first_period, MAX(dt_comptc) AS last_period, COUNT(*) AS n_obs
    FROM cvm_fi_diario
    GROUP BY cnpj
    UNION ALL
    SELECT 'fidc', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM cvm_fidc_mensal
    GROUP BY cnpj
    UNION ALL
    SELECT 'fiagro', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM cvm_fiagro_mensal
    GROUP BY cnpj
    UNION ALL
    SELECT 'fii', cnpj, 'monthly', MIN(period), MAX(period), COUNT(*)
    FROM vw_fii_mensal_latest
    GROUP BY cnpj
    UNION ALL
    SELECT 'fip', cnpj, 'yearly',
           make_date(MIN(period_year), 12, 1), make_date(MAX(period_year), 12, 1), COUNT(*)
    FROM cvm_fip_periodic
    WHERE cnpj IS NOT NULL
    GROUP BY cnpj
    UNION ALL
    SELECT 'securit', cnpj_securit, 'yearly',
           make_date(MIN(period_year), 12, 1), make_date(MAX(period_year), 12, 1), COUNT(*)
    FROM cvm_securit_mensal
    WHERE cnpj_securit IS NOT NULL
    GROUP BY cnpj_securit
)
SELECT
    entity_type,
    cnpj,
    granularity,
    first_period,
    last_period,
    n_obs,
    CASE
        WHEN granularity = 'yearly'
            THEN last_period >= make_date(EXTRACT(YEAR FROM CURRENT_DATE)::int - 1, 1, 1)
        ELSE last_period >= (date_trunc('month', CURRENT_DATE)::date - INTERVAL '3 months')
    END AS is_active
FROM activity;
