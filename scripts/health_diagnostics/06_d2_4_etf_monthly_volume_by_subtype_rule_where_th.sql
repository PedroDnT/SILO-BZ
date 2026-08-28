-- D2.4 ETF monthly volume by subtype rule (where the 2019 gap is)
SELECT date_trunc('month', trade_date)::date AS month,
  count(DISTINCT codneg) FILTER (WHERE instrument_subtype = 'etf') AS etf_tickers,
  count(DISTINCT codneg) FILTER (WHERE codbdi = '14')              AS codbdi14_tickers,
  round(sum(volume) FILTER (WHERE instrument_subtype = 'etf')/1e9, 3) AS etf_vol_bn
  FROM vw_b3_instrument_typed
  WHERE tpmerc = '010' AND trade_date BETWEEN DATE '2019-01-01' AND DATE '2020-06-30'
  GROUP BY 1 ORDER BY 1;
