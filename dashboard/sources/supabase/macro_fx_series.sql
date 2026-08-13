-- PTAX month-end sell rate per currency, last 36 months.
--
-- Month spine + LEFT JOIN, so the shape is a fixed 36 rows regardless of what
-- bacen_ptax holds (a 0-row source writes a zero-byte parquet and breaks the
-- build). Month value = the LAST quote in the month, never an average.
--
-- All rates are BRL per unit of the foreign currency, straight from PTAX.
with spine as (
  select generate_series(
           date_trunc('month', current_date) - interval '35 months',
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
monthly as (
  select distinct on (currency, date_trunc('month', reference_date))
    currency,
    date_trunc('month', reference_date)::date as period,
    buy_rate,
    sell_rate
  from bacen_ptax
  where reference_date >= (date_trunc('month', current_date) - interval '35 months')::date
  order by currency, date_trunc('month', reference_date), reference_date desc
)
select
  sp.period,
  max(m.sell_rate) filter (where m.currency = 'USD') as usd_brl,
  max(m.sell_rate) filter (where m.currency = 'EUR') as eur_brl,
  max(m.sell_rate) filter (where m.currency = 'GBP') as gbp_brl,
  max(m.sell_rate) filter (where m.currency = 'JPY') as jpy_brl,
  max(m.sell_rate) filter (where m.currency = 'ARS') as ars_brl
from spine sp
left join monthly m on m.period = sp.period
group by sp.period
order by sp.period
