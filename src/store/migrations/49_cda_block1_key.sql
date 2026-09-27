-- 49 — CDA block 1 (cvm_fi_cda): one row per government bond, not one per fund
--
-- WHY. Block 1 is one row per bond a fund holds. Its key stopped at
-- (cnpj, period, tp_aplic, tp_ativo), and TP_ATIVO reads "Título público
-- federal" for every bond, so upsert_rows (which dedupes same-key rows, last
-- write wins) kept ONE arbitrary bond per fund and application type and
-- dropped the rest with no error. Measured on CVM's own files: HIST 2015
-- 310,674 rows kept as 100,785, HIST 2020 413,549 as 140,120, 202306 42,134 as
-- 15,943 (the exact count stored), 202608 28,740 as 9,858. Issue #348.
--
-- WHAT THIS DOES
--   1. Adds typed columns for what identifies a bond: tp_fundo, tp_negoc,
--      cd_isin, cd_selic, tp_titpub, dt_venc, plus qt_pos_final.
--   2. Widens uq_fi_cda to (cnpj, period, tp_fundo, tp_aplic, tp_ativo,
--      cd_isin, tp_negoc), NULLS NOT DISTINCT. Measured 0 duplicates on HIST
--      2005, 2010, 2015, 2020 and monthly 202306, 202608 (2005 needs tp_fundo,
--      the same FI-and-FIF double filing block 4 carries it for).
--   3. Backfills the new columns from raw, one year per statement, so the
--      refill of block 1 (backfill.yml fi_doc_type) MERGES into each surviving
--      row instead of leaving it beside the rows it restores. A surviving row
--      is one real source row, so after the refill nothing is duplicated.
--
-- WHY THE KEY SWAP CANNOT COLLIDE. Every existing row is the one the old key
-- let survive, so the old four columns are already unique, and adding columns
-- to a unique key only makes collisions rarer. That stays true while the
-- backfill fills them in.
--
-- WHAT IT CANNOT DO. The dropped bonds are not in our copy. Only a re-ingest
-- of block 1 brings them back, one year per backfill.yml dispatch.
--
-- Lessons kept from migration 33: a filed value is never overwritten
-- (COALESCE), and a row is touched only when its raw actually carries the key
-- (raw ? 'CD_ISIN'). raw is not stripped here, the next ingest does that.
-- Parses that fail leave the typed column NULL and the value in raw, which is
-- what ingest's coerce() does.
--
-- Idempotent and psql -v ON_ERROR_STOP=1 clean: ADD COLUMN IF NOT EXISTS, the
-- key swap is catalog-guarded, and every backfill statement is skipped once
-- the cd_isin column comment carries the migration 49 marker (so the daily
-- re-apply does not scan the table). One statement per year keeps each round
-- trip short, because the Supabase session pooler drops a client that stays
-- silent for minutes (see #178). No semicolons in comments.

ALTER TABLE cvm_fi_cda
    ADD COLUMN IF NOT EXISTS tp_fundo     TEXT,
    ADD COLUMN IF NOT EXISTS tp_negoc     TEXT,
    ADD COLUMN IF NOT EXISTS cd_isin      TEXT,
    ADD COLUMN IF NOT EXISTS cd_selic     TEXT,
    ADD COLUMN IF NOT EXISTS tp_titpub    TEXT,
    ADD COLUMN IF NOT EXISTS dt_venc      DATE,
    ADD COLUMN IF NOT EXISTS qt_pos_final NUMERIC(28,6);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_fi_cda'::regclass
          AND conname  = 'uq_fi_cda'
          AND pg_get_constraintdef(oid) ILIKE '%cd_isin%'
    ) THEN
        ALTER TABLE cvm_fi_cda DROP CONSTRAINT IF EXISTS uq_fi_cda;
        ALTER TABLE cvm_fi_cda ADD CONSTRAINT uq_fi_cda
            UNIQUE NULLS NOT DISTINCT
            (cnpj, period, tp_fundo, tp_aplic, tp_ativo, cd_isin, tp_negoc);
    END IF;
END $$;

-- Parse helpers for the backfill, session-scoped (pg_temp) so nothing is left
-- behind. ISO first, then the Brazilian dd/mm/yyyy of older files. A value
-- neither parses as stays NULL and remains in raw.
CREATE OR REPLACE FUNCTION pg_temp.m49_date(t TEXT) RETURNS DATE
LANGUAGE plpgsql IMMUTABLE AS $f$
BEGIN
    IF t ~ '^\s*\d{4}-\d{2}-\d{2}\s*$' THEN
        RETURN btrim(t)::date;
    ELSIF t ~ '^\s*\d{2}/\d{2}/\d{4}\s*$' THEN
        RETURN to_date(btrim(t), 'DD/MM/YYYY');
    END IF;
    RETURN NULL;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN
    RETURN NULL;
END $f$;

CREATE OR REPLACE FUNCTION pg_temp.m49_num(t TEXT) RETURNS NUMERIC
LANGUAGE plpgsql IMMUTABLE AS $f$
BEGIN
    IF t ~ '^\s*-?[0-9]+(\.[0-9]+)?\s*$' THEN
        RETURN btrim(t)::numeric;
    END IF;
    RETURN NULL;
END $f$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2005-01-01' AND period < DATE '2006-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2006-01-01' AND period < DATE '2007-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2007-01-01' AND period < DATE '2008-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2008-01-01' AND period < DATE '2009-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2009-01-01' AND period < DATE '2010-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2010-01-01' AND period < DATE '2011-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2011-01-01' AND period < DATE '2012-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2012-01-01' AND period < DATE '2013-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2013-01-01' AND period < DATE '2014-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2014-01-01' AND period < DATE '2015-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2015-01-01' AND period < DATE '2016-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2016-01-01' AND period < DATE '2017-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2017-01-01' AND period < DATE '2018-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2018-01-01' AND period < DATE '2019-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2019-01-01' AND period < DATE '2020-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2020-01-01' AND period < DATE '2021-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2021-01-01' AND period < DATE '2022-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2022-01-01' AND period < DATE '2023-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2023-01-01' AND period < DATE '2024-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2024-01-01' AND period < DATE '2025-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2025-01-01' AND period < DATE '2026-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_fi_cda'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_fi_cda'::regclass AND attname = 'cd_isin')),
           '') NOT LIKE '%migration 49%' THEN
        UPDATE cvm_fi_cda
           SET tp_fundo     = COALESCE(tp_fundo,  NULLIF(btrim(COALESCE(raw ->> 'TP_FUNDO_CLASSE', raw ->> 'TP_FUNDO')), '')),
               tp_negoc     = COALESCE(tp_negoc,  NULLIF(btrim(raw ->> 'TP_NEGOC'), '')),
               cd_isin      = COALESCE(cd_isin,   NULLIF(btrim(raw ->> 'CD_ISIN'), '')),
               cd_selic     = COALESCE(cd_selic,  NULLIF(btrim(raw ->> 'CD_SELIC'), '')),
               tp_titpub    = COALESCE(tp_titpub, NULLIF(btrim(raw ->> 'TP_TITPUB'), '')),
               dt_venc      = COALESCE(dt_venc,      pg_temp.m49_date(raw ->> 'DT_VENC')),
               qt_pos_final = COALESCE(qt_pos_final, pg_temp.m49_num(raw ->> 'QT_POS_FINAL'))
         WHERE period >= DATE '2026-01-01' AND period < DATE '2027-01-01'
           AND cd_isin IS NULL
           AND raw ? 'CD_ISIN';
    END IF;
END $$;

COMMENT ON COLUMN cvm_fi_cda.cd_isin IS
  'ISIN of the government bond (migration 49). Part of uq_fi_cda with tp_fundo, tp_negoc, so each bond a fund holds is its own row. NULL only where the source row carried no CD_ISIN.';
COMMENT ON COLUMN cvm_fi_cda.tp_titpub IS
  'Title family as filed (TP_TITPUB), e.g. NOTAS DO TESOURO NACIONAL SERIE B. NTN-B and NTN-B Principal differ here and in dt_venc, not in tp_ativo.';
COMMENT ON COLUMN cvm_fi_cda.dt_venc IS
  'Maturity as filed (DT_VENC). NULL when the source value did not parse, the original then stays in raw.';
