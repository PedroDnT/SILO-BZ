select
  ticker,
  fund_name,
  provider,
  segment,
  price,
  nav,
  cotistas,
  taxa_adm_pct,
  ret_12m_pct,
  snapshot_date
from etf_market_latest
order by nav desc nulls last
