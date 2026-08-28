-- D0 contract: catalog, ticker bridge, lookup
SELECT api.catalog()->>'catalog_version' AS catalog_version,
  (SELECT count(*) FROM cia_ticker)          AS cia_ticker_rows,
  (SELECT count(*) FROM vw_company_ticker)   AS bridge_rows,
  (SELECT count(*) FROM etf_market_snapshot) AS etf_snapshot_rows;
SELECT id, name, tickers FROM api.lookup('petrobras') LIMIT 5;
