-- /options: one row per B3 session over the last 90 days of option tape.
-- Premium traded on calls (tpmerc '070') and puts ('080'), the put/call
-- premium ratio, distinct series that printed, and trades.
--
-- "Premium" is COTAHIST VOLTOT: price x quantity of the option itself, in R$.
-- It is NOT notional and NOT open interest (COTAHIST publishes no open
-- interest). Exercises print on boards 012/013 and are excluded.
--
-- ANCHOR: the window is relative to the newest option session, not
-- current_date, so a stalled ingest shows a series that stops instead of one
-- that shrinks. max(trade_date) WHERE tpmerc = '070' walks the
-- (tpmerc, trade_date DESC) index of the newest partition and returns in under
-- 1 ms; a bare max(trade_date) over the parent scans every partition (17 s,
-- measured 2026-10-23).
--
-- ZERO-ROW SAFETY: an empty tape gives zero sessions, so a NULL row is
-- appended in that case. A 0-row source writes a zero-byte parquet and breaks
-- the Evidence build.
with anchor as materialized (
  select max(trade_date) as d from b3_cotahist where tpmerc = '070'
),
agg as (
  select
    q.trade_date,
    sum(q.volume) filter (where q.tpmerc = '070') / 1e6 as call_premium_mn,
    sum(q.volume) filter (where q.tpmerc = '080') / 1e6 as put_premium_mn,
    count(distinct q.codneg)                            as n_series,
    sum(q.negocios)                                     as n_trades
  from b3_cotahist q, anchor a
  where q.tpmerc in ('070', '080')
    and q.trade_date > a.d - 90
    and q.trade_date <= a.d
  group by q.trade_date
)
select
  trade_date,
  call_premium_mn,
  put_premium_mn,
  coalesce(call_premium_mn, 0) + coalesce(put_premium_mn, 0) as total_premium_mn,
  put_premium_mn / nullif(call_premium_mn, 0)                 as put_call_ratio,
  n_series,
  n_trades
from agg
union all
select null::date, null::numeric, null::numeric, null::numeric, null::numeric, null::bigint, null::bigint
where not exists (select 1 from agg)
order by trade_date
