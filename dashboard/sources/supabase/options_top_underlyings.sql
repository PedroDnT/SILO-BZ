-- /options: the 20 underlyings with the most option premium over the last 90
-- days of option tape, with the call/put split and the latest session's share.
--
-- UNDERLYING = the first four characters of the option ticker (codneg). B3
-- builds every listed option code as the underlying's 4-letter root, a series
-- letter that encodes call/put and expiry month, and a strike number
-- (PETRK350 -> PETR). The root is shown as is: COTAHIST's nome_resumido on
-- option rows is the option's short name, not the company, so no name is
-- joined. Index options (IBOV) and ETF options (BOVA, SMAL) are roots too.
--
-- Premium is VOLTOT in R$ (price x quantity of the option itself), not
-- notional. Same anchor and window as options_daily.sql.
--
-- ZERO-ROW SAFETY: a ranked top-N over an empty table is zero rows, hence the
-- union-all fallback (same guard as b3_top_volume.sql).
with anchor as materialized (
  select max(trade_date) as d from b3_cotahist where tpmerc = '070'
),
agg as (
  select
    left(q.codneg, 4)                                            as underlying,
    sum(q.volume) / 1e6                                          as premium_mn,
    sum(q.volume) filter (where q.tpmerc = '070') / 1e6          as call_premium_mn,
    sum(q.volume) filter (where q.tpmerc = '080') / 1e6          as put_premium_mn,
    sum(q.volume) filter (where q.trade_date = a.d) / 1e6        as last_session_premium_mn,
    count(distinct q.codneg)                                     as n_series,
    sum(q.negocios)                                              as n_trades
  from b3_cotahist q, anchor a
  where q.tpmerc in ('070', '080')
    and q.trade_date > a.d - 90
    and q.trade_date <= a.d
  group by left(q.codneg, 4)
  order by sum(q.volume) desc nulls last
  limit 20
)
select
  underlying,
  premium_mn,
  call_premium_mn,
  put_premium_mn,
  put_premium_mn / nullif(call_premium_mn, 0) as put_call_ratio,
  last_session_premium_mn,
  n_series,
  n_trades
from agg
union all
select null::text, null::numeric, null::numeric, null::numeric, null::numeric, null::numeric, null::bigint, null::bigint
where not exists (select 1 from agg)
order by premium_mn desc nulls last
