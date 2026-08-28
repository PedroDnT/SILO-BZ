-- D2.8 especi x codbdi crosstab for quota-ish prints (audit before relabel)
SELECT codbdi, left(especi, 6) AS especi6, count(DISTINCT codneg) AS tickers,
  count(*) AS rows_
  FROM vw_b3_instrument_typed
  WHERE tpmerc = '010' AND (codneg LIKE '%11' OR especi ILIKE 'CI%' OR codbdi IN ('05','12','13','14'))
  AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - 400
  GROUP BY 1,2 ORDER BY rows_ DESC LIMIT 40;
