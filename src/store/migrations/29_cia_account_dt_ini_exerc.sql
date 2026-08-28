-- 29 — cia_account: DT_INI_EXERC belongs to the natural key
--
-- WHY — the same bug migration 05 fixed for DMPL, still open for the income
-- statement.
--
-- An ITR income statement publishes the SAME cd_conta twice under one filing:
-- once for the quarter and once for the year-to-date period, distinguished only
-- by DT_INI_EXERC. dt_ini_exerc is mapped to a column but was never part of
-- uq_cia_account, so the two rows shared a key and last-wins upsert kept
-- whichever the CSV happened to list last.
--
-- Measured against itr_cia_aberta_2025.zip (the published file, not our copy):
--
--   member       rows      distinct under the OLD key      lost
--   DRE_con    157,164              94,376            62,788  (40.0%)
--   BPA_con    181,930             181,674               256  ( 0.1%)
--   DFC_MI_con 139,552             139,430               122  ( 0.1%)
--   DVA_con    117,018             116,818               200  ( 0.2%)
--
-- The 40% is not noise, it is a shape: DRE_con carries 94,506 three-month rows
-- and 62,658 cumulative rows (31,632 six-month + 31,026 nine-month), and the
-- cumulative count is the loss almost exactly. Every year-to-date figure in
-- every quarterly income statement was being discarded.
--
-- The balance sheet is unaffected — BPA/BPP are point-in-time and omit
-- DT_INI_EXERC entirely, which is why their loss is 0.1% (ordinary restatement
-- duplicates, not a period collapse). DFC/DVA publish one cumulative period per
-- filing, so their periods differ by dt_refer and never collided.
--
-- Why this is not derivable after the fact: a reader cannot reconstruct the
-- cumulative by summing quarters when a company has a non-calendar fiscal year
-- (São Martinho, cd_cvm 20516, files April–March) or when an earlier quarter is
-- restated. And the surviving row was chosen by CSV ordering, not by us — a
-- value nobody decided to keep is not a value to serve.
--
-- OPERATOR NOTE — this rebuild is expensive and it is guarded for that reason.
-- Rebuilding a UNIQUE constraint on the partitioned parent validates every child
-- partition: a full scan under ACCESS EXCLUSIVE across ~31M rows / ~26 GB in 17
-- partitions. Run it when nothing else is touching the database (no Vercel
-- Evidence build — see docs/planning/STATUS_2026-08-28_day.md), and expect it to
-- take a while. The guard makes every replay after the first a no-op.
--
-- RECOVERING THE ROWS is a separate step this migration does NOT perform:
-- widening the key stops future loss, it cannot bring back rows that were
-- overwritten. Re-run the ITR backfill (entity=cia_aberta) afterwards; the rows
-- return because the upsert can finally tell the periods apart.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cia_account'::regclass
          AND conname  = 'uq_cia_account'
          AND pg_get_constraintdef(oid) ILIKE '%dt_ini_exerc%'
    ) THEN
        ALTER TABLE cia_account DROP CONSTRAINT IF EXISTS uq_cia_account;
        ALTER TABLE cia_account ADD CONSTRAINT uq_cia_account UNIQUE NULLS NOT DISTINCT
            (cd_cvm, doc_type, grupo, escopo, dt_refer, ordem_exerc, coluna_df,
             dt_ini_exerc, cd_conta, versao);
    END IF;
END $$;

COMMENT ON COLUMN cia_account.dt_ini_exerc IS
  'Start of the period a value covers. Part of the natural key (migration 29): an ITR income statement reports the same cd_conta for the quarter AND the year-to-date period, and only this column separates them. NULL for point-in-time statements (BPA/BPP).';
