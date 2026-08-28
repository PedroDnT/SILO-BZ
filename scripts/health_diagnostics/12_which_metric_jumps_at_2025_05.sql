-- D2.5b which METRIC jumps around 2025-05 (fund counts do not)
-- The reported jump is not in the number of funds: FI declines smoothly across
-- the window (25,866 -> 25,448) and FIDC's step is in January 2025, not May.
-- So the move is in a measured value. This prints every fact_fund_monthly
-- metric per family per month with its month-on-month change, so the jump can
-- be attributed to a column instead of guessed at.
--
-- Reading it: a step in n_funds means universe churn (funds entering/leaving
-- the file). A step in a per-fund average with a flat n_funds means the
-- measurement changed - a new reporting rule, a field that started being
-- filled, or a units change - and that is a data-convention question for the
-- source, never something to "smooth" here.
WITH m AS (
  SELECT
    entity_type,
    date_trunc('month', period)::date          AS month,
    count(*)                                   AS n_funds,
    sum(vl_patrim_liq) / 1e9                   AS aum_bn,
    avg(vl_patrim_liq) / 1e6                   AS avg_aum_mm,
    sum(nr_cotst)                              AS cotistas,
    avg(nr_cotst)                              AS avg_cotistas,
    count(vl_quota)                            AS with_quota,
    count(nr_cotst)                            AS with_cotistas
  FROM fact_fund_monthly
  WHERE period BETWEEN DATE '2024-10-01' AND DATE '2025-12-31'
  GROUP BY 1, 2
)
SELECT
  entity_type,
  month,
  n_funds,
  round(aum_bn, 1)                                                  AS aum_bn,
  round((aum_bn / nullif(lag(aum_bn) OVER w, 0) - 1) * 100, 1)      AS aum_mom_pct,
  round(avg_aum_mm, 2)                                              AS avg_aum_mm,
  round((avg_aum_mm / nullif(lag(avg_aum_mm) OVER w, 0) - 1) * 100, 1) AS avg_aum_mom_pct,
  cotistas,
  round((cotistas::numeric / nullif(lag(cotistas) OVER w, 0) - 1) * 100, 1) AS cotistas_mom_pct,
  with_quota,
  with_cotistas
FROM m
WINDOW w AS (PARTITION BY entity_type ORDER BY month)
ORDER BY entity_type, month;
