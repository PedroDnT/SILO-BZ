-- /dormant: the screen re-evaluated at every month-end over 36 months.
--
-- ZERO-ROW SAFETY: the row driver is a generate_series month spine anchored on
-- latest_complete_period('fi'), and fraud_screen_dormant_trend() is LEFT JOINed
-- onto it. A month the function did not return comes back NULL rather than
-- shrinking the series, so this source always emits `history` rows.
--
-- The trend function uses a RANGE frame over the period date, so a fund that
-- skipped a month has a short frame and drops out of that month's count — three
-- non-adjacent filings never pass as three consecutive months.
with params as (
  select 3 as lookback, 36 as history
),
anchor as (
  select latest_complete_period('fi') as p_end
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - (p.history - 1) * interval '1 month',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
  cross join params p
),
trend as (
  select t.*
  from params p
  cross join lateral fraud_screen_dormant_trend(p.lookback, p.history) t
)
select
  m.period,
  t.funds_filing,
  t.empty_shells,
  t.parked_capital,
  t.parked_pl / 1e9                                                    as parked_pl_bn,
  round(100.0 * t.parked_capital / nullif(t.funds_filing, 0), 1)       as parked_share_num1
from months m
left join trend t on t.period = m.period
order by m.period
