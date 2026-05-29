-- Instrument lifecycle — active vs discontinued, for survivorship-bias-free work.
-- Backed by migration 06_lifecycle.sql (cvm_fund_registry.is_active +
-- instrument_activity view) and 05_etf.sql (cvm_etf_registry).
-- Paste into psql $POSTGRES_URL -f scripts/queries/13_instrument_lifecycle.sql

-- 1) FI/FII registry: how many funds are active vs discontinued (retained)?
SELECT entity_type,
       COUNT(*)                                        AS total,
       COUNT(*) FILTER (WHERE is_active)               AS active,
       COUNT(*) FILTER (WHERE is_active IS FALSE)      AS discontinued,
       COUNT(*) FILTER (WHERE is_active IS NULL)       AS status_unknown
FROM cvm_fund_registry
GROUP BY entity_type
ORDER BY entity_type;

-- 2) Cross-entity activity derived from actual reporting (covers FIDC/FIP/
--    FIAGRO/SECURIT, which have no cadastral file). Active vs discontinued.
SELECT entity_type, granularity,
       COUNT(*)                              AS instruments,
       COUNT(*) FILTER (WHERE is_active)     AS active,
       COUNT(*) FILTER (WHERE NOT is_active) AS discontinued,
       MIN(first_period)                     AS earliest,
       MAX(last_period)                      AS latest
FROM instrument_activity
GROUP BY entity_type, granularity
ORDER BY entity_type;

-- 3) Discontinued instruments that still carry history (the point of retention):
--    most recently delisted, with how long they reported.
SELECT entity_type, cnpj, first_period, last_period, n_obs
FROM instrument_activity
WHERE NOT is_active
ORDER BY last_period DESC
LIMIT 50;

-- 4) Discontinued ETFs (retained in cvm_etf_registry with dt_cancel)
SELECT ticker, fund_name, underlying_index, situacao, dt_cancel
FROM cvm_etf_registry
WHERE is_active IS FALSE
ORDER BY dt_cancel DESC NULLS LAST;
