-- 52 — SECURIT: every filed row lands, and the securitizer is mapped
--
-- WHY (issue #349). upsert_rows dedupes rows that share a conflict key, last
-- write wins, with no error. The three SECURIT keys were coarser than what CVM
-- files, measured on the real 2026 files:
--   cvm_securit_dfin    (instrument_type, period_year, cnpj_securit) with a
--                       NULL CNPJ kept ONE row per year of each type: 302 CRA
--                       and 933 CRI filings stored as 1 and 1.
--   cvm_securit_mensal  no certificate in the key, so reports sharing a month
--                       and an issue value collapsed: 347 CRA, 575 CRI, 2 OTS.
--   cvm_securit_serie   no Classe in the key: 10 CRA, 185 CRI, 211 OTS.
--
-- WHY (issue #350). CRA and CRI name the securitizer CNPJ_Emissora, which no
-- field map listed, so cnpj_securit is NULL on every CRA and CRI row of the
-- three tables. OTS uses CNPJ_Securitizadora and was already mapped.
--
-- THE NEW KEYS
--   mensal  (instrument_type, codigo_identificacao, dt_emissao, occurrence)
--   serie   (instrument_type, codigo_identificacao, data_referencia,
--            numero_serie, classe, occurrence)
--   dfin    (instrument_type, codigo_identificacao, data_referencia, occurrence)
-- dt_emissao is the mensal column that holds Data_Referencia (a legacy name).
-- Measured on the 2019, 2022 and 2026 files of all three types: every
-- distinct source row keeps its own key, 0 lost.
--
-- WHY occurrence. Even with Classe, CVM files several different rows for one
-- series and class (2026: 66 CRI and 33 OTS groups, up to 16 rows) and, once,
-- two different reports for one certificate-month (OTS 2026, CRA 2019). No
-- column tells them apart. Ingest numbers them 1..k in the order of their
-- content, so a re-ingest of the same file lands on the same keys. A row_hash
-- in the key would not do: 12 to 19% of monthly reports are re-filed, and a
-- re-filed report would land beside its first version and double every sum.
-- Numbered, version 2 overwrites version 1 as it always has.
--
-- WHY cnpj_securit IS NOT IN ANY KEY
--   1. In every file measured a certificate-month names exactly one
--      securitizer, so the CNPJ separates nothing the certificate does not.
--   2. Existing CRA and CRI rows cannot get it back from raw. The old ingest
--      stripped CNPJ_Emissora from raw (pg_client._strip_raw_duplicates drops
--      every raw key naming a CNPJ when the table has a CNPJ column). With the
--      CNPJ in the key, the re-ingest would insert every CRA and CRI row beside
--      its NULL-CNPJ twin. Out of the key, its DO UPDATE fills it in place.
--   3. Certificates change securitizer (318 CRI codes across 2019 to 2026).
--      That is an attribute of the report, not a new document.
--
-- Versao is stored as a column, not keyed. Each yearly file carries one
-- version of each report, the latest, so keying on it would only keep a
-- restated v1 beside its v2.
--
-- WHAT THIS DOES
--   1. Adds the columns: codigo_identificacao, versao, occurrence (mensal),
--      versao, occurrence (serie), codigo_identificacao, data_referencia,
--      versao, occurrence (dfin).
--   2. Backfills codigo_identificacao, data_referencia and versao from raw on
--      mensal and dfin, where the old ingest left them. serie already has
--      every key column, and its versao is filled by the re-ingest, which
--      spares a rewrite of the largest of the three tables.
--   3. Numbers occurrence inside every group of the new key that holds more
--      than one existing row, in the order of raw, then id.
--   4. Swaps the three unique keys, NULLS NOT DISTINCT like the keys they
--      replace, so a row whose classe or numero_serie is empty still matches
--      itself on the next ingest.
--
-- WHY THE SWAP CANNOT COLLIDE. After step 3 every group of the new key holds
-- rows numbered 1..k, so the new key is unique by construction.
--
-- WHAT IT CANNOT DO. The rows the old keys dropped are not in our copy, and
-- existing CRA and CRI rows still have a NULL CNPJ. The securit re-ingest
-- (backfill.yml, entity securit, every year) restores the one and fills the
-- other on every row it matches. An existing row the re-ingest does not match
-- (a group CVM now files with fewer rows) keeps its values and its NULL CNPJ.
-- Nothing is deleted here.
--
-- Idempotent and psql -v ON_ERROR_STOP=1 clean: ADD COLUMN IF NOT EXISTS, the
-- key swaps are catalog-guarded, and every backfill and numbering statement is
-- skipped once its table's occurrence column comment carries the migration 52
-- marker, so the daily re-apply does not scan the tables. The mensal backfill
-- runs one year per statement to keep each round trip short, because the
-- Supabase session pooler drops a client that stays silent for minutes (#178).
-- No semicolons in comments.

ALTER TABLE cvm_securit_mensal
    ADD COLUMN IF NOT EXISTS codigo_identificacao TEXT,
    ADD COLUMN IF NOT EXISTS versao               INT,
    ADD COLUMN IF NOT EXISTS occurrence           SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE cvm_securit_serie
    ADD COLUMN IF NOT EXISTS versao     INT,
    ADD COLUMN IF NOT EXISTS occurrence SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE cvm_securit_dfin
    ADD COLUMN IF NOT EXISTS codigo_identificacao TEXT,
    ADD COLUMN IF NOT EXISTS data_referencia      DATE,
    ADD COLUMN IF NOT EXISTS versao               INT,
    ADD COLUMN IF NOT EXISTS occurrence           SMALLINT NOT NULL DEFAULT 1;

-- Parse helpers for the backfill, session-scoped (pg_temp) so nothing is left
-- behind. A value that does not parse stays NULL and remains in raw, which is
-- what ingest's coerce() does.
CREATE OR REPLACE FUNCTION pg_temp.m52_date(t TEXT) RETURNS DATE
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

CREATE OR REPLACE FUNCTION pg_temp.m52_int(t TEXT) RETURNS INT
LANGUAGE plpgsql IMMUTABLE AS $f$
BEGIN
    IF t ~ '^\s*\d{1,9}\s*$' THEN
        RETURN btrim(t)::int;
    END IF;
    RETURN NULL;
END $f$;

-- Step 2, mensal: one statement per period_year, then everything outside the
-- range in one more, so no year is left with a NULL certificate.

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2016
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2017
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2018
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2019
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2020
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2021
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2022
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2023
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2024
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2025
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2026
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE period_year = 2027
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE (period_year < 2016 OR period_year > 2027)
           AND ((codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
             OR (versao IS NULL AND raw ? 'Versao'));
    END IF;
END $$;

-- Step 2, dfin: a few rows per year, one statement.
DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_dfin'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_dfin'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_dfin
           SET codigo_identificacao = COALESCE(codigo_identificacao, NULLIF(btrim(raw ->> 'Codigo_Identificacao_Certificado'), '')),
               data_referencia      = COALESCE(data_referencia, pg_temp.m52_date(raw ->> 'Data_Referencia')),
               versao               = COALESCE(versao, pg_temp.m52_int(raw ->> 'Versao'))
         WHERE (codigo_identificacao IS NULL AND raw ? 'Codigo_Identificacao_Certificado')
            OR (data_referencia IS NULL AND raw ? 'Data_Referencia')
            OR (versao IS NULL AND raw ? 'Versao');
    END IF;
END $$;

-- Step 3: number the groups of the new key that hold more than one existing
-- row. PARTITION BY puts NULLs in one group, as NULLS NOT DISTINCT will.

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_mensal'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_mensal'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_mensal t
           SET occurrence = n.rn
          FROM (
                SELECT id,
                       row_number() OVER (PARTITION BY instrument_type, codigo_identificacao, dt_emissao ORDER BY raw::text, id) AS rn,
                       count(*)     OVER (PARTITION BY instrument_type, codigo_identificacao, dt_emissao)                         AS k
                  FROM cvm_securit_mensal
               ) n
         WHERE n.id = t.id
           AND n.k > 1
           AND t.occurrence IS DISTINCT FROM n.rn;
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_serie'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_serie'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_serie t
           SET occurrence = n.rn
          FROM (
                SELECT id,
                       row_number() OVER (PARTITION BY instrument_type, codigo_identificacao, data_referencia, numero_serie, classe ORDER BY raw::text, id) AS rn,
                       count(*)     OVER (PARTITION BY instrument_type, codigo_identificacao, data_referencia, numero_serie, classe)                         AS k
                  FROM cvm_securit_serie
               ) n
         WHERE n.id = t.id
           AND n.k > 1
           AND t.occurrence IS DISTINCT FROM n.rn;
    END IF;
END $$;

DO $$
BEGIN
    IF COALESCE(col_description('cvm_securit_dfin'::regclass,
           (SELECT attnum FROM pg_attribute
             WHERE attrelid = 'cvm_securit_dfin'::regclass AND attname = 'occurrence')),
           '') NOT LIKE '%migration 52%' THEN
        UPDATE cvm_securit_dfin t
           SET occurrence = n.rn
          FROM (
                SELECT id,
                       row_number() OVER (PARTITION BY instrument_type, codigo_identificacao, data_referencia ORDER BY raw::text, id) AS rn,
                       count(*)     OVER (PARTITION BY instrument_type, codigo_identificacao, data_referencia)                         AS k
                  FROM cvm_securit_dfin
               ) n
         WHERE n.id = t.id
           AND n.k > 1
           AND t.occurrence IS DISTINCT FROM n.rn;
    END IF;
END $$;

-- Step 4: the key swaps.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_securit_mensal'::regclass
          AND conname  = 'uq_securit_mensal'
          AND pg_get_constraintdef(oid) ILIKE '%occurrence%'
    ) THEN
        ALTER TABLE cvm_securit_mensal DROP CONSTRAINT IF EXISTS uq_securit_mensal;
        ALTER TABLE cvm_securit_mensal ADD CONSTRAINT uq_securit_mensal
            UNIQUE NULLS NOT DISTINCT (instrument_type, codigo_identificacao, dt_emissao, occurrence);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_securit_serie'::regclass
          AND conname  = 'uq_securit_serie'
          AND pg_get_constraintdef(oid) ILIKE '%occurrence%'
    ) THEN
        ALTER TABLE cvm_securit_serie DROP CONSTRAINT IF EXISTS uq_securit_serie;
        ALTER TABLE cvm_securit_serie ADD CONSTRAINT uq_securit_serie
            UNIQUE NULLS NOT DISTINCT (instrument_type, codigo_identificacao, data_referencia, numero_serie, classe, occurrence);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'cvm_securit_dfin'::regclass
          AND conname  = 'uq_securit_dfin'
          AND pg_get_constraintdef(oid) ILIKE '%occurrence%'
    ) THEN
        ALTER TABLE cvm_securit_dfin DROP CONSTRAINT IF EXISTS uq_securit_dfin;
        ALTER TABLE cvm_securit_dfin ADD CONSTRAINT uq_securit_dfin
            UNIQUE NULLS NOT DISTINCT (instrument_type, codigo_identificacao, data_referencia, occurrence);
    END IF;
END $$;

-- The occurrence comments are the backfill markers, so they are set last.
COMMENT ON COLUMN cvm_securit_mensal.codigo_identificacao IS
  'Codigo_Identificacao_Certificado as filed: the certificate this monthly report is about (migration 52). Part of uq_securit_mensal.';
COMMENT ON COLUMN cvm_securit_mensal.versao IS
  'Versao as filed. Stored, not keyed: each yearly file carries one version of each report, the latest. NULL where the source row carried none.';
COMMENT ON COLUMN cvm_securit_mensal.dt_emissao IS
  'Data_Referencia, the month the report covers. A legacy name, not an issue date.';
COMMENT ON COLUMN cvm_securit_mensal.dt_vencto IS
  'Always NULL: the monthly report (ativo_passivo) has no maturity column in any layout. Series maturity is cvm_securit_serie.data_vencimento.';
COMMENT ON COLUMN cvm_securit_mensal.occurrence IS
  '1, 2, ... among different reports CVM files for the same certificate-month, numbered in content order (migration 52). 1 on almost every row.';
COMMENT ON COLUMN cvm_securit_serie.versao IS
  'Versao as filed. Stored, not keyed: each yearly file carries one version of each report, the latest. NULL on rows the securit re-ingest has not rewritten since migration 52.';
COMMENT ON COLUMN cvm_securit_serie.occurrence IS
  '1, 2, ... among different rows CVM files for the same series and class in one monthly report, numbered in content order (migration 52). Byte-identical repeats are kept once.';
COMMENT ON COLUMN cvm_securit_dfin.codigo_identificacao IS
  'Codigo_Identificacao_Certificado as filed: the certificate these statements belong to (migration 52). Part of uq_securit_dfin.';
COMMENT ON COLUMN cvm_securit_dfin.data_referencia IS
  'Data_Referencia as filed: the statements'' reference date. NULL where it did not parse, the original then stays in raw.';
COMMENT ON COLUMN cvm_securit_dfin.versao IS
  'Versao as filed. Stored, not keyed: each yearly file carries one version of each filing, the latest. NULL where the source row carried none.';
COMMENT ON COLUMN cvm_securit_dfin.occurrence IS
  '1, 2, ... among different filings for the same certificate and reference date (migration 52). 1 on every row measured.';
