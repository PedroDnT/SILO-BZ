-- Driven from cvm_etf_registry (not etf_market_latest) so this source always
-- yields rows.
--
-- etf_market_latest is FROM etf_market_snapshot LEFT JOIN cvm_etf_registry, and
-- etf_market_snapshot stays empty until the APIFY_TOKEN-gated etfsbrasil scrape
-- runs — so the view returns 0 rows on a token-less deploy. Evidence writes a
-- zero-byte file for a 0-row source, and the build then dies reading it back:
--
--     Invalid Input Error: File 'supabase_etf_market.parquet' too small to be a
--     Parquet file
--
-- Flipping the join direction keeps the ETF universe (the registry is populated
-- by its own backfill job) as the row driver and leaves every market column
-- NULL until a snapshot exists. Absent data reads as absent — never as a guess —
-- and the section fills in on its own once the scrape lands.
select
  r.ticker,
  coalesce(m.fund_name, r.fund_name) as fund_name,
  r.provider,
  r.segment,
  m.price,
  m.nav,
  m.cotistas,
  m.taxa_adm_pct,
  m.ret_12m_pct,
  m.snapshot_date
from cvm_etf_registry r
left join etf_market_latest m on m.ticker = r.ticker
order by m.nav desc nulls last, r.ticker
