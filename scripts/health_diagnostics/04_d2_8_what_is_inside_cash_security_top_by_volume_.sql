-- D2.8 what is inside cash_security (top by volume, last 90 sessions)
SELECT codneg, especi, codbdi, sum(volume)/1e6 AS vol_mm, count(*) AS sessions
  FROM vw_b3_instrument_typed
  WHERE instrument_type = 'cash_security' AND tpmerc = '010'
  AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - 130
  GROUP BY 1,2,3 ORDER BY vol_mm DESC NULLS LAST LIMIT 25;
