-- D2.10 quotaholders coverage by family (nr_cotst)
SELECT entity_type, count(*) AS rows_, count(nr_cotst) AS with_cotistas,
  max(period) AS last_period
  FROM fact_fund_monthly GROUP BY 1 ORDER BY 1;
