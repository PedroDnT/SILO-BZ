-- Migration 62: retire cvm_fi_balancete, the account-level FI balancete.
--
-- WHY. It held every COFI account every fund files, about 2.2M rows a month
-- since 2019: 31 GB, 27% of the database on 2026-10-01, and nothing read it.
-- Its group totals and fee accounts live in cvm_fi_balancete_resumo
-- (migrations 59 and 61), which the ingest now writes alone. The owner approved
-- retiring it behind that summary on 2026-10-01 (docs/planning/OPEN_ITEMS.md
-- item 10). CVM still publishes the files, so any account can be re-fetched.
--
-- WHY TRUNCATE, NOT DROP. Every daily run re-applies schema.sql and every
-- migration, and migration 22 runs ALTER TABLE cvm_fi_balancete, which would
-- fail on a dropped table (historical migrations are never edited). TRUNCATE
-- returns the table's disk to the operating system at once and leaves an
-- empty table those statements still apply to.
--
-- GUARD. The table is emptied only when every month it holds has rows in
-- cvm_fi_balancete_resumo. scripts/backfill_balancete_summary.py builds a
-- month in one statement, so a month with any summary rows is complete. The
-- months are read with a loose scan of idx_fi_balancete_date (one index probe
-- per month), never a full scan. If a month is missing, nothing is truncated
-- and a NOTICE names the months: run daily_ingest mode=balancete-summary and
-- the next schema apply finishes the job. Once the table is empty this file is
-- a no-op.

DO $$
DECLARE
    missing  text;
    n_months int;
BEGIN
    IF to_regclass('public.cvm_fi_balancete') IS NULL
       OR to_regclass('public.cvm_fi_balancete_resumo') IS NULL THEN
        RETURN;
    END IF;

    WITH RECURSIVE m AS (
        SELECT max(dt_comptc) AS d FROM cvm_fi_balancete
        UNION ALL
        SELECT (SELECT max(b.dt_comptc) FROM cvm_fi_balancete b WHERE b.dt_comptc < m.d)
        FROM m
        WHERE m.d IS NOT NULL
    )
    SELECT count(*),
           string_agg(to_char(d, 'YYYY-MM-DD'), ', ' ORDER BY d)
               FILTER (WHERE NOT EXISTS (
                   SELECT 1 FROM cvm_fi_balancete_resumo r WHERE r.dt_comptc = m.d))
      INTO n_months, missing
    FROM m
    WHERE d IS NOT NULL;

    IF n_months = 0 THEN
        RETURN;   -- already empty
    END IF;

    IF missing IS NOT NULL THEN
        RAISE NOTICE 'cvm_fi_balancete kept: no summary rows yet for %. Run daily_ingest mode=balancete-summary.', missing;
        RETURN;
    END IF;

    EXECUTE 'TRUNCATE TABLE cvm_fi_balancete';
    RAISE NOTICE 'cvm_fi_balancete emptied: all % months are in cvm_fi_balancete_resumo.', n_months;
END $$;

COMMENT ON TABLE cvm_fi_balancete IS
    'Retired by migration 62: emptied once cvm_fi_balancete_resumo covered every stored month; the ingest writes only the summary. Kept as an empty table because migration 22 alters it on every schema apply.';
