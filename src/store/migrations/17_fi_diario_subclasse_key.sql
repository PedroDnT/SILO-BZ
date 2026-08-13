-- CVM-175 (2025+) fund classes can carry multiple subclasses under one
-- CNPJ_FUNDO_CLASSE, each filing its own daily NAV/quota/flow row. The
-- previous UNIQUE (cnpj, dt_comptc) key could not tell them apart: the second
-- subclasse silently overwrote the first on every upsert (last-write-wins in
-- src/store/pg_client.py's pre-upsert dedup).
--
-- Verified against a live 2025-06 CVM inf_diario file: on 2025-06-30, 1,418 of
-- 25,046 distinct CNPJ_FUNDO_CLASSE values had 2+ rows that date; 75 of those
-- were genuinely distinct subclasses (e.g. CNPJ 00.888.897/0001-13 carries
-- subclasses RBMFN... at ~R$36.6mm and MZMRC... at ~R$995mm — two different
-- pools of money that were colliding into one row). Column added NOT NULL
-- DEFAULT '' (not NULL) so the widened UNIQUE constraint still catches
-- duplicates for the ~95% of funds with no subclasse — Postgres treats NULL
-- as distinct from NULL in a UNIQUE constraint, which would have silently
-- reopened the same collision for every non-subclassed fund.
--
-- The remaining ~1,343 same-day collisions are a different, CVM-side
-- artifact: the same CNPJ reported under two TP_FUNDO_CLASSE labels ("FI" and
-- "CLASSES - FIF", i.e. legacy vs CVM-175) with an empty ID_SUBCLASSE on both
-- rows — not addressed by this migration; see ingest_fi.py for how ingest
-- now picks between them deterministically.
ALTER TABLE cvm_fi_diario ADD COLUMN IF NOT EXISTS id_subclasse TEXT NOT NULL DEFAULT '';

-- Guarded, same pattern as 03_precision.sql's retypes and for the same
-- reason: this file is re-applied on every ingest run (schema.sql +
-- migrations run every time, not once), and an unguarded ADD CONSTRAINT on a
-- partitioned table with years of cvm_fi_diario history forces Postgres to
-- re-validate uniqueness across the ENTIRE table on every single run, not
-- just the first — the DROP+ADD ran unconditionally, so every apply after
-- the first paid a full-table scan for no reason. Skips entirely once the
-- constraint already covers id_subclasse.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.key_column_usage
        WHERE table_schema = 'public'
          AND table_name = 'cvm_fi_diario'
          AND constraint_name = 'uq_fi_diario'
          AND column_name = 'id_subclasse'
    ) THEN
        ALTER TABLE cvm_fi_diario DROP CONSTRAINT IF EXISTS uq_fi_diario;
        ALTER TABLE cvm_fi_diario ADD CONSTRAINT uq_fi_diario UNIQUE (cnpj, dt_comptc, id_subclasse);
    END IF;
END $$;
