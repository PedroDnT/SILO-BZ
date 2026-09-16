-- MAIOR SIR — top 20 by days to cover (short quantity / 21-session ADTV).
--
-- Two filters that are the difference between a risk screen and a curiosity:
--
--   * Equities only. Unfiltered, this list is entirely index ETFs — PIBB11 at
--     110 days, BOVA11 at 32 — because they are held on loan against thin
--     secondary volume. True, and not what "crowded short" means.
--   * A floor on the position size. A R$50k short on an illiquid name produces
--     a huge, meaningless ratio.
--
-- adtv_sessions is carried through so a ratio computed over a short window is
-- visible as such rather than presented with false precision.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    row_number() over (order by s.days_to_cover desc) as rank,
    s.codneg                                          as ticker,
    s.asset_name,
    s.days_to_cover,
    s.short_brl,
    s.adtv_brl_21,
    s.adtv_sessions,
    s.pct_float,
    s.float_basis
  from fact_short_interest_daily s
  where s.trade_date = (select max(trade_date) from fact_short_interest_daily)
    and s.days_to_cover is not null
    and s.categoria in ('SHARES', 'UNIT')
    and s.short_brl >= 5000000
  order by s.days_to_cover desc
  limit 20
)
select * from rows_
union all
select null::bigint, null::text, null::text, null::numeric, null::numeric, null::numeric, null::bigint, null::numeric, null::text
where not exists (select 1 from rows_)
