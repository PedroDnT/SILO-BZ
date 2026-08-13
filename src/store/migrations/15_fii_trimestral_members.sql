-- 15_fii_trimestral_members.sql — model the FII INF_TRIMESTRAL archive properly
--
-- ============================================================================
-- WHY: cvm_fii_periodic rows labelled doc_type='trimestral' DO NOT CONTAIN
--      QUARTERLY REPORTS
-- ============================================================================
-- src/fetchers/cvm_config.py configured FII `trimestral` with
--     csv_name_pattern = "inf_trimestral_fii_{year}.csv"
-- and that member has never existed. The real archive
-- (inf_trimestral_fii_{year}.zip) holds 16 members; verified against the live
-- 2025 file on 2026-08-13:
--
--     inf_trimestral_fii_alienacao_imovel_2025.csv     <- alphabetically FIRST
--     inf_trimestral_fii_alienacao_terreno_2025.csv
--     inf_trimestral_fii_aquisicao_imovel_2025.csv
--     inf_trimestral_fii_aquisicao_terreno_2025.csv
--     inf_trimestral_fii_ativo_2025.csv
--     inf_trimestral_fii_ativo_garantia_rentabilidade_2025.csv
--     inf_trimestral_fii_complemento_2025.csv
--     inf_trimestral_fii_direito_2025.csv
--     inf_trimestral_fii_geral_2025.csv
--     inf_trimestral_fii_imovel_2025.csv
--     inf_trimestral_fii_imovel_desempenho_2025.csv
--     inf_trimestral_fii_imovel_renda_acabado_contrato_2025.csv
--     inf_trimestral_fii_imovel_renda_acabado_inquilino_2025.csv
--     inf_trimestral_fii_rentabilidade_efetiva_2025.csv
--     inf_trimestral_fii_resultado_contabil_financeiro_2025.csv
--     inf_trimestral_fii_terreno_2025.csv
--
-- The fetcher used to fall back to "the first CSV in the archive" when the
-- configured name matched nothing, so every trimestral ingest actually parsed
-- inf_trimestral_fii_alienacao_imovel_{year}.csv — a register of properties the
-- fund SOLD (Nome_Imovel, Endereco, Data_Alienacao, Area, Numero_Unidades,
-- Percentual_Imovel_PL). Those are the columns an earlier migration lifted onto
-- cvm_fii_periodic, which is why the property-shaped columns are there.
--
-- ---------------------------------------------------------------------------
-- OPERATOR ACTION REQUIRED — pre-existing rows are mislabelled, NOT deleted here
-- ---------------------------------------------------------------------------
-- Every cvm_fii_periodic row with doc_type='trimestral' written before this
-- migration came from the ALIENACAO_IMOVEL member, not from a quarterly report.
-- They are real CVM data under the wrong label. This migration deliberately does
-- not touch them: dropping data is the operator's call, not a migration's.
-- Inspect them with
--     SELECT period_year, count(*) FROM cvm_fii_periodic
--      WHERE doc_type = 'trimestral' GROUP BY 1 ORDER BY 1;
-- and then either
--     (a) purge, once the new trimestral_geral / trimestral_complemento /
--         trimestral_imovel doc_types have been backfilled:
--             DELETE FROM cvm_fii_periodic WHERE doc_type = 'trimestral';
--  or (b) relabel, to keep the alienacao history under an honest name:
--             UPDATE cvm_fii_periodic SET doc_type = 'trimestral_alienacao_imovel'
--              WHERE doc_type = 'trimestral';
--         (no alienacao ingest is wired, so nothing will refresh those rows)
-- Leaving them as-is keeps a provenance lie in the table, so do one or the other.
--
-- The `trimestral` doc_type itself is gone from cvm_config.py and dispatch.py,
-- replaced by trimestral_geral / trimestral_complemento / trimestral_imovel, and
-- a csv_name_pattern that matches no member is now a hard error in the fetcher
-- instead of a silent substitution.
--
-- All statements are idempotent single statements, psql -v ON_ERROR_STOP=1 clean.

-- ---------------------------------------------------------------------------
-- 1. Widen the cvm_fii_periodic key with data_referencia
--
--    The old key (cnpj, doc_type, period_year) assumed one row per fund per
--    year. That is wrong for two of the three periodic doc_types:
--      * trimestral_* is QUARTERLY — the real 2025 geral member has 4,577 rows
--        over 1,329 funds and 5 reference dates, so 3 of every 4 quarters would
--        be overwritten by the next upsert,
--      * dfin ships several filings per fund per year (e.g. 00.332.266/0001-31
--        appears for both 2025-07-31 and 2025-12-31 in dfin_fii_2025.csv).
--    Adding data_referencia keeps NULLS NOT DISTINCT, so rows that carry no
--    reference date behave exactly as before. Widening a unique key can never
--    fail on existing data: it only makes collisions rarer.
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_fii_periodic DROP CONSTRAINT IF EXISTS uq_fii_periodic;

ALTER TABLE cvm_fii_periodic
    ADD CONSTRAINT uq_fii_periodic UNIQUE NULLS NOT DISTINCT
        (cnpj, doc_type, period_year, data_referencia);

-- ---------------------------------------------------------------------------
-- 2. Typed columns for the GERAL and COMPLEMENTO members
--    (see src/parsers/field_maps/fii_trimestral_geral.py / _complemento.py)
-- ---------------------------------------------------------------------------
ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS versao              INT,
    ADD COLUMN IF NOT EXISTS data_entrega        DATE,
    ADD COLUMN IF NOT EXISTS nome_fundo          TEXT,
    ADD COLUMN IF NOT EXISTS tp_fundo            TEXT,
    ADD COLUMN IF NOT EXISTS publico_alvo        TEXT,
    ADD COLUMN IF NOT EXISTS codigo_isin         TEXT,
    ADD COLUMN IF NOT EXISTS cotas_emitidas      NUMERIC(28,8),
    ADD COLUMN IF NOT EXISTS fundo_exclusivo     BOOLEAN,
    ADD COLUMN IF NOT EXISTS mandato             TEXT,
    ADD COLUMN IF NOT EXISTS segmento_atuacao    TEXT,
    ADD COLUMN IF NOT EXISTS tipo_gestao         TEXT,
    ADD COLUMN IF NOT EXISTS prazo_duracao       TEXT,
    ADD COLUMN IF NOT EXISTS nome_administrador  TEXT,
    ADD COLUMN IF NOT EXISTS cnpj_administrador  TEXT;

ALTER TABLE cvm_fii_periodic
    ADD COLUMN IF NOT EXISTS pr_indexador_igpm                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_inpc                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_ipca                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS pr_indexador_incc                NUMERIC(20,8),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_disponibilidades  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_titulos_publicos  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_titulos_privados  NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ativo_liquidez_fundos_renda_fixa NUMERIC(20,6);

CREATE INDEX IF NOT EXISTS idx_fii_periodic_segmento
    ON cvm_fii_periodic (segmento_atuacao) WHERE segmento_atuacao IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. cvm_fii_imovel — the property register, a NEW GRAIN
--
--    Many properties per fund per quarter (20,227 rows for 2025 alone), so it
--    cannot share cvm_fii_periodic's one-row-per-fund-per-period key.
--
--    row_hash: CVM ships no property identifier and the source legitimately
--    repeats identical descriptive rows (one fund reports five indistinguishable
--    460 m2 units in the same building for the same quarter). Measured on the
--    real 2025 member, every descriptive key collides — (cnpj, data_referencia,
--    nome_imovel) 302 times, and even adding versao + classe + endereco + area +
--    numero_unidades still collides 135 times — which under ON CONFLICT DO UPDATE
--    would silently drop ~260 real rows a year. A sha256 over the row's own
--    source fields collides 0 times, invents nothing, and makes re-ingesting an
--    unchanged file an exact no-op. See src/parsers/field_maps/fii_imovel.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cvm_fii_imovel (
    id                  BIGSERIAL    PRIMARY KEY,
    cnpj                TEXT         NOT NULL CHECK (char_length(cnpj) = 14),
    data_referencia     DATE         NOT NULL,
    row_hash            TEXT         NOT NULL,   -- sha256 of the source row (see above)
    versao              INT,
    classe              TEXT,                    -- e.g. "Imoveis para renda acabados"
    nome_imovel         TEXT,
    endereco            TEXT,
    area                NUMERIC(20,6),
    numero_unidades     INT,
    outras_caracteristicas TEXT,
    pr_vacancia         NUMERIC(20,8),
    pr_inadimplencia    NUMERIC(20,8),
    pr_receitas_fii     NUMERIC(20,8),
    pr_locado           NUMERIC(20,8),
    pr_vendido          NUMERIC(20,8),
    pr_conclusao_obras_realizado NUMERIC(20,8),
    pr_conclusao_obras_previsto  NUMERIC(20,8),
    custo_construcao_realizado   NUMERIC(20,6),
    custo_construcao_previsto    NUMERIC(20,6),
    pr_imovel_total_investido    NUMERIC(20,8),
    period_year         INT          NOT NULL,   -- archive year, injected by the ingest
    raw                 JSONB        NOT NULL,
    fetched_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fii_imovel UNIQUE (cnpj, data_referencia, row_hash)
);

CREATE INDEX IF NOT EXISTS idx_fii_imovel_cnpj   ON cvm_fii_imovel (cnpj);

CREATE INDEX IF NOT EXISTS idx_fii_imovel_period ON cvm_fii_imovel (data_referencia DESC);

CREATE INDEX IF NOT EXISTS idx_fii_imovel_classe ON cvm_fii_imovel (classe) WHERE classe IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fii_imovel_vacancia
    ON cvm_fii_imovel (data_referencia DESC) WHERE pr_vacancia IS NOT NULL;
