-- /options: option premium traded over the last 90 days of tape, by the
-- option's expiry month (data_vencimento) and by calls vs puts.
--
-- Shows where activity sits along the expiry calendar: most premium trades in
-- the nearest one or two monthly expiries. An option that expired inside the
-- window still counts in its own expiry month. A row with no published
-- data_vencimento is dropped and not guessed.
--
-- Premium is VOLTOT in R$, not notional. Same anchor and window as
-- options_daily.sql.
--
-- ZERO-ROW SAFETY: union-all NULL row when the window holds no option rows.
with anchor as materialized (
  select max(trade_date) as d from b3_cotahist where tpmerc = '070'
),
agg as (
  select
    date_trunc('month', q.data_vencimento)::date                         as expiry_month,
    case q.tpmerc when '070' then 'Call' else 'Put' end                   as side,
    sum(q.volume) / 1e6                                                   as premium_mn,
    count(distinct q.codneg)                                              as n_series
  from b3_cotahist q, anchor a
  where q.tpmerc in ('070', '080')
    and q.trade_date > a.d - 90
    and q.trade_date <= a.d
    and q.data_vencimento is not null
  group by 1, 2
)
select expiry_month, side, premium_mn, n_series
from agg
union all
select null::date, null::text, null::numeric, null::bigint
where not exists (select 1 from agg)
order by expiry_month, side
