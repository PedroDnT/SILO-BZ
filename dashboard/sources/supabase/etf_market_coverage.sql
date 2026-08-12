select
  count(*)               as etfs_with_snapshot,
  count(nav)             as with_nav,
  count(price)           as with_price,
  count(cotistas)        as with_cotistas,
  max(snapshot_date)     as latest_snapshot
from etf_market_latest
