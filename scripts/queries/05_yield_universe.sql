-- Cross-domain yield universe: FII + FIAGRO + CRA + CRI vs CDI
-- Paste into Supabase SQL editor or: psql $SUPABASE_DB_URL -f scripts/queries/05_yield_universe.sql
--
-- Fetch current CDI monthly rate from BCB API before running:
--   curl "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/1?formato=json"
--   Returns: [{"data":"14/05/2026","valor":"0.08218"}]  ← use that valor as decimal

-- Last 12 months, with CDI spread (replace 0.084 with live CDI monthly %)
SELECT * FROM yield_universe(
  ARRAY['fii', 'fiagro'],
  ARRAY['cra_classe', 'cri_classe'],
  CURRENT_DATE - 365,
  CURRENT_DATE,
  0.084   -- monthly CDI % — replace with live value from BCB API above
)
ORDER BY period DESC, spread_vs_benchmark DESC NULLS LAST;

-- Without benchmark (just yields, no spread)
SELECT * FROM yield_universe(
  ARRAY['fii', 'fiagro'],
  ARRAY['cra_classe', 'cri_classe'],
  CURRENT_DATE - 365,
  CURRENT_DATE
)
ORDER BY period DESC, yield_mes DESC NULLS LAST;

-- Latest period only — top 50 ranked by yield
SELECT * FROM yield_universe(
  ARRAY['fii', 'fiagro'],
  ARRAY['cra_classe', 'cri_classe'],
  (SELECT MAX(period) FROM fact_fund_monthly),
  CURRENT_DATE
)
ORDER BY yield_mes DESC NULLS LAST
LIMIT 50;
