-- 14_fi_perfil_columns.sql — lift the unmapped PERFIL_MENSAL columns out of raw JSONB
--
-- WHY
-- ---
-- cvm_fi_perfil already carried 9 typed columns that NO field map wrote
-- (pr_ativo_cred_priv, pr_patrim_liq_maior_cotst, the 7 nr_cotst_* buckets, …):
-- the values existed in every source CSV but sat only in `raw`, so the typed
-- columns were permanently NULL and every /fi dashboard query had to scan JSONB.
-- The FIELD_MAP is extended in the same change (src/parsers/field_maps/fi_perfil.py);
-- this migration adds the columns that map now needs.
--
-- WHAT THE SOURCE ACTUALLY SHIPS (verified against the real files, not guessed)
-- ---------------------------------------------------------------------------
-- perfil_mensal_fi_202512.csv has 107 fields, perfil_mensal_fi_202012.csv has 106.
-- The only header that changed with CVM-175 is the key: CNPJ_FUNDO -> CNPJ_FUNDO_CLASSE
-- (plus the added TP_FUNDO_CLASSE). Every column added below is spelled identically
-- in both vintages, so no legacy aliases are needed for them.
--
--   16 investor-type headcounts  NR_COTST_*      (the pre-existing 7 columns omitted
--                                                 NR_COTST_PF_VAREJO — retail individuals,
--                                                 the single most important bucket — plus
--                                                 the pension/insurance/foreign buckets)
--   16 matching share-of-PL      PR_PL_COTST_*   (headcount != money: one PF_PB cotista
--                                                 can hold more PL than 10k varejo ones)
--   concentration                PR_COMITENTE_1..3, COMITENTE_LIGADO_1..3
--   liquidity                    NR_DIA_CINQU_PERC, NR_DIA_CEM_PERC, ST_LIQDEZ,
--                                PR_PATRIM_LIQ_CONVTD_CAIXA
--
-- PR_ATIVO_EMISSOR_LIGADO and PR_PATRIM_LIQ_MAIOR_COTST already exist (added by an
-- earlier ALTER block in schema.sql) and are only newly *mapped* — no DDL here.
--
-- BACKFILL
-- --------
-- Existing rows keep NULL in the new columns until their month is re-ingested;
-- the values are still in `raw`, so nothing is lost and nothing is fabricated.
-- The dashboard sources coalesce(typed, raw->>…) for exactly that reason.
--
-- All statements are idempotent single statements (no semicolons inside comments)
-- so the file is psql -v ON_ERROR_STOP=1 clean.

-- --------------------------------------------------------------------------
-- Investor headcount by type (NR_COTST_*) — 9 buckets missing from the schema
-- --------------------------------------------------------------------------
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS nr_cotst_pf_varejo            INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_corretora_distrib    INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_invnr                INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_eapc                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_efpc                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_rpps                 INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_segur                INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_capitaliz            INT,
    ADD COLUMN IF NOT EXISTS nr_cotst_outro                INT;

-- --------------------------------------------------------------------------
-- Share of PL by investor type (PR_PL_COTST_*) — all 16, none existed before
-- --------------------------------------------------------------------------
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pf_pb                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pf_varejo             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_nao_financ_pb      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_nao_financ_varejo  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_banco                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_corretora_distrib     NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_pj_financ             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_invnr                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_eapc                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_efpc                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_rpps                  NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_segur                 NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_capitaliz             NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_fi_clube              NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_distrib               NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_pl_cotst_outro                 NUMERIC(20,8);

-- --------------------------------------------------------------------------
-- Concentration: the three largest comitentes (share of PL + related-party flag)
-- --------------------------------------------------------------------------
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS pr_comitente_1      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_comitente_2      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_comitente_3      NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS comitente_ligado_1  BOOLEAN,
    ADD COLUMN IF NOT EXISTS comitente_ligado_2  BOOLEAN,
    ADD COLUMN IF NOT EXISTS comitente_ligado_3  BOOLEAN;

-- --------------------------------------------------------------------------
-- Liquidity: days to liquidate 50% / 100% of the book, self-declared adequacy,
-- and the share of PL convertible to cash
-- --------------------------------------------------------------------------
ALTER TABLE cvm_fi_perfil
    ADD COLUMN IF NOT EXISTS nr_dia_cinqu_perc            NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS nr_dia_cem_perc              NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS st_liqdez                    TEXT,
    ADD COLUMN IF NOT EXISTS pr_patrim_liq_convtd_caixa   NUMERIC(20,8);

-- --------------------------------------------------------------------------
-- Indexes for the retail-vs-institutional and concentration reads
-- --------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_fi_perfil_pf_varejo
    ON cvm_fi_perfil (period DESC) WHERE nr_cotst_pf_varejo IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fi_perfil_maior_cotst
    ON cvm_fi_perfil (period DESC) WHERE pr_patrim_liq_maior_cotst IS NOT NULL;
