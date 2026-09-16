-- ADTV Mensal — average daily traded value on the cash market, R$ bn.
--
-- Computed from our own tape, not from B3's AverageChart table, for one reason
-- that matters: AverageChart only ever returns a trailing 12 months, while
-- b3_cotahist goes back to 2019 in this warehouse (and to 1986 at the source).
-- The two agree where they overlap; this one keeps the history.
--
-- Reads mv_b3_monthly_activity rather than the tape directly — the same
-- partition-pruning lesson b3_market_overview documents, where a full-tape scan
-- cost a 4.4-minute production build.
--
-- Zero-row safe: returns no rows on a fresh database, which the page renders as
-- an empty chart rather than failing the build.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    a.period                                as month,
    a.volume / nullif(a.n_sessions, 0) / 1e9 as adtv_brl_bn,
    a.n_sessions,
    a.n_tickers
  from mv_b3_monthly_activity a
  where a.grain = 'segment'
    and a.market_segment = 'cash'
    and a.n_sessions > 0
  order by a.period
)
select * from rows_
union all
select null::date, null::numeric, null::bigint, null::bigint
where not exists (select 1 from rows_)
