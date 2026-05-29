-- ETF (Fundo de Índice) overview — registry + AUM/quotaholders/NAV/returns.
-- Backed by migration 05_etf.sql (cvm_etf_registry + etf_daily / etf_latest views).
-- Paste into psql $POSTGRES_URL -f scripts/queries/12_etf_overview.sql

-- 1) The curated ETF universe with enriched attributes + lifecycle
SELECT ticker, cnpj, fund_name, provider, underlying_index, segment,
       situacao, is_active, dt_cancel, classe_anbima, taxa_adm, taxa_perfm
FROM cvm_etf_registry
ORDER BY is_active DESC NULLS LAST, segment, ticker;

-- 2) Latest snapshot per ETF: AUM, quotaholders, NAV, last flow
SELECT ticker, underlying_index, segment, dt_comptc,
       vl_quota          AS nav_quota,
       aum,
       quotaholders,
       net_flow,
       taxa_adm
FROM etf_latest
ORDER BY aum DESC NULLS LAST;

-- 3) Coverage check: which seeded ETFs actually have inf_diario data?
--    (rows = ETFs whose CNPJ resolves in cvm_fi_diario)
SELECT e.ticker, e.cnpj,
       COUNT(d.dt_comptc)        AS days,
       MIN(d.dt_comptc)          AS first_day,
       MAX(d.dt_comptc)          AS last_day
FROM cvm_etf_registry e
LEFT JOIN cvm_fi_diario d ON d.cnpj = e.cnpj
GROUP BY e.ticker, e.cnpj
ORDER BY days DESC;

-- 4) Trailing 30-observation cumulative return per ETF (from daily quota)
SELECT ticker, underlying_index,
       EXP(SUM(LN(1 + daily_return))) - 1 AS ret_last_30_obs
FROM (
    SELECT ticker, underlying_index, daily_return,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY dt_comptc DESC) AS rn
    FROM etf_daily
    WHERE daily_return IS NOT NULL
) s
WHERE rn <= 30
GROUP BY ticker, underlying_index
ORDER BY ret_last_30_obs DESC NULLS LAST;
