-- /risk: where the daily return variance of each IBOV member lives, from
-- mv_risk_decompose_ibov (44_api_risk_decompose.sql): api.risk_decompose with
-- its defaults (252 returns to the last IBOV session, sector leg from the CVM
-- setor map) for every member of B3's IBOV theoretical portfolio on the newest
-- reference date held. Shares are fractions of the stock's variance and add to
-- 1; a member with no sector index has sector_share NULL (two parts). A member
-- the function refused keeps its refusal text and NULL shares.
--
-- ZERO-ROW SAFETY: the view is empty on a fresh database (no portfolio rows),
-- and a zero-row source writes the 0-byte parquet that kills the whole Evidence
-- build, hence the union-all fallback (same guard as b3_top_volume.sql).
with r as (
  select
    ticker,
    asset_name,
    ibov_weight,
    portfolio_date,
    status,
    refusal,
    sector_leg,
    setor_current,
    window_from,
    window_to,
    n_returns,
    stock_series,
    market_share,
    sector_share,
    residual_share,
    vol_total,
    beta_market,
    beta_sector,
    hedge_ibov,
    hedge_sector,
    ex_shock_market_share,
    ex_shock_residual_share,
    shock_sensitive,
    illiquid,
    flags,
    built_at
  from mv_risk_decompose_ibov
)
select * from r
union all
select null::text, null::text, null::numeric, null::date, null::text, null::text,
       null::text, null::text, null::date, null::date, null::int, null::text,
       null::numeric, null::numeric, null::numeric, null::numeric, null::numeric,
       null::numeric, null::numeric, null::numeric, null::numeric, null::numeric,
       null::boolean, null::boolean, null::text, null::timestamptz
where not exists (select 1 from r)
order by ibov_weight desc nulls last, ticker
