-- 50 — cia_filing: a NULL versao no longer defeats the natural key
--
-- WHY. uq_cia_filing is (cd_cvm, doc_type, dt_refer, versao), NULLS DISTINCT
-- by default, and versao is nullable. ingest_cia_filing keeps a summary row
-- whose VERSAO is empty (the version is left NULL, never guessed), so every
-- re-run of the same ITR/DFP year would insert that filing again beside the
-- last copy instead of updating it: not idempotent. cia_account already uses
-- NULLS NOT DISTINCT for the same reason. Issue/PR #37.
--
-- WHAT THIS DOES. Recreates uq_cia_filing on the same columns with
-- NULLS NOT DISTINCT. Same name and columns, so the ON CONFLICT column list in
-- src/parsers/field_maps/cia_filing.py CONFLICT still resolves to it.
--
-- WHY IT CANNOT COLLIDE. Measured on production 2026-09-28: 23,862 rows,
-- 0 with versao NULL, so treating NULLs as equal merges nothing.
--
-- Idempotent and psql -v ON_ERROR_STOP=1 clean: the swap runs only while the
-- constraint is not yet NULLS NOT DISTINCT.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cia_filing'::regclass
          AND conname  = 'uq_cia_filing'
          AND pg_get_constraintdef(oid) ILIKE '%NULLS NOT DISTINCT%'
    ) THEN
        ALTER TABLE cia_filing DROP CONSTRAINT IF EXISTS uq_cia_filing;
        ALTER TABLE cia_filing ADD CONSTRAINT uq_cia_filing
            UNIQUE NULLS NOT DISTINCT (cd_cvm, doc_type, dt_refer, versao);
    END IF;
END $$;
