-- Latest PTAX quote per currency, with the published bid-ask spread.
--
-- Driven from the literal currency list in PTAX_CURRENCIES
-- (src/pipeline/bacen_pipeline.py), so this always returns 5 rows and a
-- currency that failed to ingest appears as an explicit blank line instead of
-- shrinking the result to zero rows and breaking the build.
--
-- spread_num2 = (sell − buy) / sell, in percentage points of the sell rate.
-- buy_rate / sell_rate are BACEN's own PTAX compra/venda, unadjusted.
with currencies (currency) as (
  values ('USD'), ('EUR'), ('GBP'), ('JPY'), ('ARS')
)
select
  c.currency,
  p.reference_date,
  p.buy_rate,
  p.sell_rate,
  round(100.0 * (p.sell_rate - p.buy_rate) / nullif(p.sell_rate, 0), 2) as spread_num2,
  (current_date - p.reference_date) as days_stale,
  n.n_obs
from currencies c
left join lateral (
  select b.reference_date, b.buy_rate, b.sell_rate
  from bacen_ptax b
  where b.currency = c.currency
  order by b.reference_date desc
  limit 1
) p on true
left join lateral (
  select count(*) as n_obs
  from bacen_ptax b
  where b.currency = c.currency
) n on true
order by c.currency
