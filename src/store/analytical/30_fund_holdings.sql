-- =============================================================================
-- 30_fund_holdings.sql
-- Materialized view: mv_fund_holdings_monthly, what funds hold, per month,
-- from the CDA blocks 4 (cvm_fi_cda_acoes) and 2 (cvm_fi_cda_cotas), 2019 on.
--
-- WHY A MATVIEW. Neither table has an index on period, and they are 12 GB and
-- 10 GB, so every query over one month is a full scan (over a minute each, read
-- on 2026-10-01). The /holdings sources read this instead: one scan per table
-- per apply, a few MB for the dashboard.
--
-- KINDS (one long table, told apart by `kind`):
--   'stock'      key = cd_ativo, the B3 ticker. tp_aplic 'Ações', 'Ações e
--                outros TVM cedidos em empréstimo' (shares lent out are still
--                owned) and 'Certificado ou recibo de depósito de valores
--                mobiliários' (units). Not borrowed shares ('Obrigações por
--                ações e outros TVM recebidos em empréstimo' is a liability),
--                options, futures or BDRs.
--   'debenture'  key = the issuer's B3 code, characters 3-6 of the ISIN
--                (BRTAEEDBS0O9 -> TAEE). tp_aplic 'Debêntures'. Block 4 carries
--                the debentures funds hold: R$788.9bn on 2026-05, against
--                R$34.4bn in block 6 (cvm_fi_cda_debentures). No company name
--                is joined: the code is what the source publishes.
--   'quota'      month totals only (key always NULL): fund quotas held by
--                funds, and the part flagged emissor_ligado = 'S' (same
--                economic group). On 2026-05 that part was R$4.03tn of
--                R$6.12tn, held by 13,705 of 20,529 funds: mostly feeder funds
--                holding their own manager's master fund, an ordinary
--                structure, so no per-fund rows are kept.
-- A row with key NULL is the month's total for its kind: n_funds there counts
-- distinct filing funds, which the per-key rows cannot be summed into.
--
-- COLUMNS. n_funds: distinct funds (per key: holding it; per total: filing).
-- n_assets: distinct tickers / debenture codes / held funds. vl_total: sum of
-- vl_merc_pos_final. vl_related: the part flagged emissor_ligado = 'S'.
--
-- COMPLETENESS IS NOT DECIDED HERE. CVM's newest months fill in late (from
-- 2026-06 about half the funds, issue #476), so readers pick the last month
-- whose total n_funds reaches 90% of the prior year's median, as
-- rates_ntnb_fund_holdings.sql does.
--
-- Same session settings as 04_fact_fund_monthly.sql (LOCAL timeout, no
-- parallel workers, no JIT) for the same memory reasons. Nothing depends on it,
-- so a plain DROP is enough; the drop and create are one transaction.
-- =============================================================================

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL max_parallel_workers_per_gather = 0;
SET LOCAL jit = off;

DROP MATERIALIZED VIEW IF EXISTS mv_fund_holdings_monthly;

CREATE MATERIALIZED VIEW mv_fund_holdings_monthly AS
WITH block4 AS (
  SELECT
    CASE
      WHEN tp_aplic IN (
        'Ações',
        'Ações e outros TVM cedidos em empréstimo',
        'Certificado ou recibo de depósito de valores mobiliários'
      ) THEN 'stock'
      WHEN tp_aplic = 'Debêntures' THEN 'debenture'
    END                                       AS kind,
    period,
    CASE
      WHEN tp_aplic = 'Debêntures' THEN substring(cd_isin FROM 3 FOR 4)
      ELSE cd_ativo
    END                                       AS key,
    cnpj,
    cd_ativo                                  AS asset,
    vl_merc_pos_final                         AS v,
    emissor_ligado
  FROM cvm_fi_cda_acoes
  WHERE period >= DATE '2019-01-01'
    AND tp_aplic IN (
      'Ações',
      'Ações e outros TVM cedidos em empréstimo',
      'Certificado ou recibo de depósito de valores mobiliários',
      'Debêntures'
    )
),
block4_agg AS (
  SELECT
    kind, period, key,
    count(DISTINCT cnpj)                                    AS n_funds,
    count(DISTINCT asset)                                   AS n_assets,
    sum(v)                                                  AS vl_total,
    sum(v) FILTER (WHERE emissor_ligado = 'S')              AS vl_related
  FROM block4
  WHERE key IS NOT NULL
  GROUP BY GROUPING SETS ((kind, period, key), (kind, period))
),
quota_agg AS (
  SELECT
    'quota'::text                                           AS kind,
    period,
    NULL::text                                              AS key,
    count(DISTINCT cnpj)                                    AS n_funds,
    count(DISTINCT cnpj_cota)                               AS n_assets,
    sum(vl_merc_pos_final)                                  AS vl_total,
    sum(vl_merc_pos_final) FILTER (WHERE emissor_ligado = 'S') AS vl_related
  FROM cvm_fi_cda_cotas
  WHERE period >= DATE '2019-01-01'
  GROUP BY period
)
SELECT kind, period, key, n_funds, n_assets, vl_total, vl_related FROM block4_agg
UNION ALL
SELECT kind, period, key, n_funds, n_assets, vl_total, vl_related FROM quota_agg;

CREATE INDEX ix_mv_fund_holdings_monthly ON mv_fund_holdings_monthly (kind, period);

COMMENT ON MATERIALIZED VIEW mv_fund_holdings_monthly IS
    'What funds hold per month from CDA blocks 4 and 2, 2019 on (analytical file 30). kind stock (key = ticker), debenture (key = issuer code from the ISIN) or quota (month totals only). key NULL = the month''s total for the kind. Newest months are incomplete; pick the month by the total n_funds.';

COMMIT;
