-- D2.8 classification: how BOVA11 / IBOV11 / IVVB11 actually print
SELECT codneg, tpmerc, codbdi, especi, isin, instrument_type, instrument_subtype,
  count(*) AS sessions, min(trade_date) AS first_seen, max(trade_date) AS last_seen
  FROM vw_b3_instrument_typed
  WHERE codneg IN ('BOVA11','IBOV11','IVVB11','SMAL11','BOVV11','KNRI11','BPAC11')
  GROUP BY 1,2,3,4,5,6,7 ORDER BY codneg, last_seen DESC;
