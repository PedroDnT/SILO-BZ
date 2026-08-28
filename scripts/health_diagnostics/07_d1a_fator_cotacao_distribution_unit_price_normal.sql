-- D1a fator_cotacao distribution (unit-price normalization)
SELECT fator_cotacao, count(DISTINCT codneg) AS tickers, count(*) AS rows_
  FROM b3_cotahist
  WHERE tpmerc = '010' AND trade_date > (SELECT max(trade_date) FROM b3_cotahist) - 400
  GROUP BY 1 ORDER BY rows_ DESC LIMIT 10;
