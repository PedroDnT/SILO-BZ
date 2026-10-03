-- Migration 66: cvm_fi_extrato, the Extrato das Informacoes each fund or class files with CVM.
--
-- WHY. The lamina (migration 65) carries a TAXA_ADM for only 15.9% of the 26,046
-- active FI funds (4,135), and cad_fi (migration 64) for 7 of 25,178. The Extrato
-- (dados.cvm.gov.br/dataset/fi-doc-extrato) carries one for 21,962 of the 26,046
-- (84.3%; 84.5% of the funds with PL >= R$1M), including the CVM 175 classes, plus
-- the performance fee, entry and exit fees, the custody fee, the redemption terms
-- and CLASSE_ANBIMA. Measured on a GitHub Actions runner, 2026-10-03 (issue #524,
-- run 37090491647, throwaway branch research/extrato-coverage). Owner decision on
-- issue #515 (2026-10-03): the Extrato is the primary disclosed-fee source, the
-- lamina second, cad_fi third. Header and types: src/parsers/field_maps/fi_extrato.py.
--
-- SOURCE. Two plain CSVs (latin-1, ';', 117 columns). extrato_fi.csv is the
-- current file, one row per fund or class CNPJ (38,796 rows, refreshed daily);
-- extrato_fi_YYYY.csv holds every version filed in a year (several rows per CNPJ,
-- refreshed weekly). There is no subclass column: a CVM 175 row is the class.
--
-- KEY. (CNPJ_FUNDO_CLASSE, DT_COMPTC), both NOT NULL, so a plain UNIQUE. One row
-- per CNPJ in the current file is measured; uniqueness of the pair inside the
-- yearly files is NOT measured (2025 has up to 20 rows per CNPJ). The ingest keeps
-- the last row of a repeated pair and logs how many it collapsed.
--
-- READ IT THROUGH vw_fi_extrato_latest: the newest dt_comptc per CNPJ, with
-- age_days. Reading the table directly returns every version.
--
-- AS FILED. taxa_adm is stored exactly as the source gives it. 16.7% of the values
-- are exactly 0 and 115 are above 5 (maximum 14,638.38, scale errors). They are
-- NOT rewritten here: the rules that read a 0 as "not informed" and refuse a value
-- above 5 are applied when reading (api.portfolio_fees), never to the stored value.
--
-- STORAGE. `raw` keeps the 70 PR_* exposure limits and the other unmapped columns,
-- as text. The current file is about 34 MB; the yearly files 6 to 12 MB each.
--
-- Landing tables carry no client grant (12_grants_and_rls.sql).

BEGIN;

CREATE TABLE IF NOT EXISTS cvm_fi_extrato (
    id           BIGSERIAL,
    cnpj         TEXT        NOT NULL CHECK (char_length(cnpj) = 14),
    dt_comptc    DATE        NOT NULL,    -- DT_COMPTC as filed, not normalised
    source_file  TEXT,                    -- extrato_fi.csv or extrato_fi_YYYY.csv: which file this version came from
    tp_fundo_classe              TEXT,
    denom_social                 TEXT,
    condom                       TEXT,
    publico_alvo                 TEXT,
    reg_anbima                   TEXT,
    classe_anbima                TEXT,
    fundo_cotas                  TEXT,
    taxa_adm                     NUMERIC,
    taxa_custodia_max            NUMERIC,
    existe_taxa_perfm            TEXT,
    taxa_perfm                   NUMERIC,
    param_taxa_perfm             TEXT,
    pr_indice_refer_taxa_perfm   NUMERIC,
    calc_taxa_perfm              TEXT,
    inf_taxa_perfm               TEXT,
    existe_taxa_ingresso         TEXT,
    taxa_ingresso_real           NUMERIC,
    taxa_ingresso_pr             NUMERIC,
    existe_taxa_saida            TEXT,
    taxa_saida_real              NUMERIC,
    taxa_saida_pr                NUMERIC,
    taxa_saida_pagto_resgate     TEXT,
    aplic_min                    NUMERIC,
    qt_dia_conversao_cota        NUMERIC,
    qt_dia_pagto_cota            NUMERIC,
    qt_dia_resgate_cotas         NUMERIC,
    qt_dia_pagto_resgate         NUMERIC,
    tp_dia_pagto_resgate         TEXT,
    raw          JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fi_extrato UNIQUE (cnpj, dt_comptc)
);
CREATE INDEX IF NOT EXISTS ix_fi_extrato_date ON cvm_fi_extrato (dt_comptc DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON cvm_fi_extrato FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON TABLE cvm_fi_extrato IS
    'CVM Extrato das Informacoes (extrato_fi.csv and extrato_fi_YYYY.csv), one row per fund or class CNPJ and DT_COMPTC, as filed (migration 66). The fees and terms are the fund''s own declaration; there is no subclass column. Read the current one through vw_fi_extrato_latest.';
COMMENT ON COLUMN cvm_fi_extrato.dt_comptc IS
    'DT_COMPTC: date of the document (data de competencia do documento), as filed. It is the date of the filed version, not how old the information is.';
COMMENT ON COLUMN cvm_fi_extrato.source_file IS
    'The CSV this row was read from: extrato_fi.csv (current snapshot) or extrato_fi_YYYY.csv (a year of versions).';
COMMENT ON COLUMN cvm_fi_extrato.tp_fundo_classe IS
    'TP_FUNDO_CLASSE: FI (ICVM 555 fund) or CLASSES - FIF (CVM 175 class), as filed.';
COMMENT ON COLUMN cvm_fi_extrato.denom_social IS
    'DENOM_SOCIAL, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.condom IS
    'CONDOM: ABERTO or FECHADO, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.publico_alvo IS
    'PUBLICO_ALVO: target investors, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.reg_anbima IS
    'REG_ANBIMA: S or N, whether the fund is registered with ANBIMA, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.classe_anbima IS
    'CLASSE_ANBIMA: the ANBIMA classification, as filed (98.9% filled for the active funds).';
COMMENT ON COLUMN cvm_fi_extrato.fundo_cotas IS
    'FUNDO_COTAS: S or N, whether it is a fund of funds, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_adm IS
    'TAXA_ADM: the administration fee exactly as filed. The dictionary states no unit; CVM''s XML standard says percent a year (base 252) for investors that are not qualified, and the balancete estimate agrees (median ratio 0.994). Exactly 0 for 16.7% of the active funds and above 5 for 115 (maximum 14,638.38): both are stored as filed and handled when read, never rewritten. NULL = the cell was empty or not a number (then raw->''_unparsed'' holds it).';
COMMENT ON COLUMN cvm_fi_extrato.taxa_custodia_max IS
    'TAXA_CUSTODIA_MAX: maximum custody fee, as filed (decimal 15,6); the dictionary states no unit.';
COMMENT ON COLUMN cvm_fi_extrato.existe_taxa_perfm IS
    'EXISTE_TAXA_PERFM: S or N, whether the fund charges a performance fee, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_perfm IS
    'TAXA_PERFM: the performance fee rate as filed (numeric 27,12). Filled when existe_taxa_perfm = S (24.8% of the active funds).';
COMMENT ON COLUMN cvm_fi_extrato.param_taxa_perfm IS
    'PARAM_TAXA_PERFM: the benchmark the performance fee is charged over, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.pr_indice_refer_taxa_perfm IS
    'PR_INDICE_REFER_TAXA_PERFM: percent of the reference index the performance fee is charged over, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.calc_taxa_perfm IS
    'CALC_TAXA_PERFM: the performance fee calculation method, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.inf_taxa_perfm IS
    'INF_TAXA_PERFM: additional information on the performance fee, free text as filed.';
COMMENT ON COLUMN cvm_fi_extrato.existe_taxa_ingresso IS
    'EXISTE_TAXA_INGRESSO: S or N, whether the fund charges an entry fee, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_ingresso_real IS
    'TAXA_INGRESSO_REAL: entry fee in reais, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_ingresso_pr IS
    'TAXA_INGRESSO_PR: entry fee in percent, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.existe_taxa_saida IS
    'EXISTE_TAXA_SAIDA: S or N, whether the fund charges an exit fee, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_saida_real IS
    'TAXA_SAIDA_REAL: exit fee in reais, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.taxa_saida_pr IS
    'TAXA_SAIDA_PR: exit fee in percent, as filed (filled for 3.3% of the active funds).';
COMMENT ON COLUMN cvm_fi_extrato.taxa_saida_pagto_resgate IS
    'TAXA_SAIDA_PAGTO_RESGATE: S or N, whether an exit fee applies on the payment of redemptions, as filed. A flag, not a rate.';
COMMENT ON COLUMN cvm_fi_extrato.aplic_min IS
    'APLIC_MIN: minimum subscription, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.qt_dia_conversao_cota IS
    'QT_DIA_CONVERSAO_COTA: business days from the redemption request to quota conversion (D+n quote), as filed.';
COMMENT ON COLUMN cvm_fi_extrato.qt_dia_pagto_cota IS
    'QT_DIA_PAGTO_COTA: business days from quota conversion to payment of the redemption, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.qt_dia_resgate_cotas IS
    'QT_DIA_RESGATE_COTAS: days of lock-up (carencia) for redemption, as filed; filled for 2.9% of the active funds.';
COMMENT ON COLUMN cvm_fi_extrato.qt_dia_pagto_resgate IS
    'QT_DIA_PAGTO_RESGATE: days from the redemption request to payment, counted as tp_dia_pagto_resgate says, as filed.';
COMMENT ON COLUMN cvm_fi_extrato.tp_dia_pagto_resgate IS
    'TP_DIA_PAGTO_RESGATE: the kind of day qt_dia_pagto_resgate counts, as filed.';

CREATE OR REPLACE VIEW vw_fi_extrato_latest
WITH (security_invoker = true) AS
SELECT DISTINCT ON (e.cnpj)
       e.*,
       (CURRENT_DATE - e.dt_comptc)::int AS age_days
  FROM cvm_fi_extrato e
 ORDER BY e.cnpj, e.dt_comptc DESC, e.fetched_at DESC, e.id DESC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON vw_fi_extrato_latest FROM anon, authenticated';
    END IF;
END $$;

COMMENT ON VIEW vw_fi_extrato_latest IS
    'The newest cvm_fi_extrato version per CNPJ, with age_days, the days between its dt_comptc and today. A fund that never filed an Extrato has no row; an old one shows its age, never a guessed current value (migration 66).';

COMMIT;
