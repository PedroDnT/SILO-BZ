-- Fund name exploration: search by manager, coverage check, status breakdown
-- Paste into psql $POSTGRES_URL -f scripts/queries/09_fund_names.sql

-- Search by fund manager name (case-insensitive, all entity types)
SELECT cnpj, entity_type, fund_name, latest_aum FROM search_funds('kinea', NULL, 10);
SELECT cnpj, entity_type, fund_name, latest_aum FROM search_funds('btg', NULL, 10);
SELECT cnpj, entity_type, fund_name, latest_aum FROM search_funds('xp', 'fidc', 10);

-- All funds for a given manager ranked by latest AUM
SELECT d.cnpj, d.entity_type, d.fund_name, d.status, f.latest_aum
FROM dim_fund d
LEFT JOIN LATERAL (
  SELECT vl_patrim_liq AS latest_aum
  FROM fact_fund_monthly
  WHERE cnpj = d.cnpj AND vl_patrim_liq IS NOT NULL
  ORDER BY period DESC LIMIT 1
) f ON TRUE
WHERE d.fund_name ILIKE '%kinea%'
ORDER BY f.latest_aum DESC NULLS LAST;

-- Name coverage by entity type
SELECT entity_type,
       COUNT(*)                                              AS total_funds,
       COUNT(fund_name)                                     AS with_name,
       ROUND(COUNT(fund_name)::numeric / COUNT(*) * 100, 1) AS pct_named
FROM dim_fund
GROUP BY entity_type ORDER BY entity_type;

-- Cancelled / liquidated funds that are still reporting data (data lag indicator)
SELECT d.cnpj, d.entity_type, d.fund_name, d.status, d.last_period
FROM dim_fund d
WHERE d.status IN ('CANCELADO', 'LIQUIDADO ANTECIPADAMENTE')
  AND d.last_period >= CURRENT_DATE - 180
ORDER BY d.last_period DESC
LIMIT 20;

-- FI fund status breakdown from cadastral
SELECT status, COUNT(*) AS n_funds
FROM dim_fund WHERE entity_type = 'fi' AND status IS NOT NULL
GROUP BY status ORDER BY n_funds DESC;
