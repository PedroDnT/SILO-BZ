---
title: Risk Decomposition
hide_title: true
sidebar_position: 6
---

<!--
  Where the daily return variance of each IBOV member lives: market (IBOV),
  sector (a B3 sector index made orthogonal to IBOV) and residual (the part
  specific to the stock). One row per member of B3's IBOV theoretical
  portfolio on the newest reference date, from mv_risk_decompose_ibov, which
  runs api.risk_decompose with its defaults (44_api_risk_decompose.sql).

  WHAT A READER MUST KNOW, stated in the lede:
    * Realized and historical: the last 252 daily returns. Hedge ratios are
      neutralization math for that window, not trade advice.
    * The sector leg is SILO's map from the company's CVM setor to a B3 sector
      index, not index membership. A setor with no index (oil, telecom,
      transport, health, ...) has no sector leg: two parts only.
    * One shock session (the 2026-10-26 election session) can dominate a
      1-year window; the ex-shock columns repeat the split without it.

  ZERO-ROW SAFETY: the source has a union-all fallback (one NULL row on an
  empty database), so every query below filters `ticker is not null`.
-->

```sql risk_all
select
  ticker,
  asset_name,
  ibov_weight,
  sector_leg,
  setor_current,
  status,
  n_returns,
  window_from,
  window_to,
  stock_series,
  market_share * 100            as market_percent,
  sector_share * 100            as sector_percent,
  residual_share * 100          as residual_percent,
  ex_shock_market_share * 100   as ex_shock_market_percent,
  ex_shock_residual_share * 100 as ex_shock_residual_percent,
  vol_total * 100               as vol_total_percent,
  beta_market,
  beta_sector,
  hedge_ibov,
  hedge_sector,
  flags,
  refusal,
  portfolio_date,
  built_at
from supabase.risk_decompose_ibov
where ticker is not null
order by ibov_weight desc nulls last, ticker
```

```sql risk_headline
select
  count(*)                                                    as members,
  count(*) filter (where status = 'ok')                       as decomposed,
  count(*) filter (where status is distinct from 'ok')        as not_decomposed,
  median(residual_share) filter (where status = 'ok') * 100   as median_residual_percent,
  max(window_to)                                              as window_to,
  max(portfolio_date)                                         as portfolio_date
from supabase.risk_decompose_ibov
where ticker is not null
```

```sql risk_top_long
select ticker, part, share_percent, ibov_weight
from (
  select ticker, ibov_weight, 'Market (IBOV)' as part, market_share * 100 as share_percent
  from supabase.risk_decompose_ibov where status = 'ok'
  union all
  select ticker, ibov_weight, 'Sector', coalesce(sector_share, 0) * 100
  from supabase.risk_decompose_ibov where status = 'ok'
  union all
  select ticker, ibov_weight, 'Residual', residual_share * 100
  from supabase.risk_decompose_ibov where status = 'ok'
) x
where ticker in (
  select ticker from supabase.risk_decompose_ibov
  where status = 'ok'
  order by ibov_weight desc nulls last, ticker
  limit 25
)
order by ibov_weight desc nulls last, ticker
```

```sql risk_not_decomposed
select ticker, asset_name, ibov_weight, coalesce(status, 'refused') as status, n_returns, refusal
from supabase.risk_decompose_ibov
where ticker is not null and status is distinct from 'ok'
order by ibov_weight desc nulls last, ticker
```

# Risk Decomposition

> How much of each Ibovespa member's daily return variance comes from the
> market (IBOV), from its sector, and from the stock itself. The last 252
> daily returns, dividends reinvested, for every member of B3's IBOV portfolio.
>
> **Realized and historical only.** Hedge ratios say how much IBOV and sector
> index per R$ 1 long would have neutralized those legs in this window. They
> are not trade advice.
>
> The sector leg is a fixed map from the company's CVM sector to a B3 sector
> index (IFNC financials, IMAT materials, IEEX electric power, UTIL sanitation,
> IMOB construction, ICON consumer). It is **not index membership**. A sector
> with no index (oil and gas, telecom, transport, health) has no sector leg, so
> its split has two parts. A stock that is a large member of its own sector
> index puts part of its own risk in the sector share.
>
> One shock day can dominate a 1-year window (the 2026-10-26 election session:
> IBOV -13.9%). The ex-shock columns repeat the split without those sessions.
> Method and every input: the `risk_decompose` endpoint
> (`/v2/prices?id=ITUB4&kind=risk`).

<BigValue data={risk_headline} value=members title="IBOV Members" fmt=num0/>
<BigValue data={risk_headline} value=decomposed title="Decomposed" fmt=num0/>
<BigValue data={risk_headline} value=median_residual_percent title="Median Residual Share (%)" fmt=num1/>
<BigValue data={risk_headline} value=window_to title="Window Ends"/>

---

## The 25 Largest Members

> Each bar is 100% of the stock's variance. A long residual segment means an
> IBOV or sector hedge removes little of the risk.

<BarChart
  data={risk_top_long}
  x=ticker
  y=share_percent
  series=part
  type=stacked
  swapXY=true
  sort=false
  yAxisTitle="Share of Variance (%)"
  title="Share of Daily Return Variance, 25 Largest IBOV Weights"
/>

---

## Every Member

> Betas are OLS on daily returns: `beta_market` to IBOV, `beta_sector` to the
> sector index after its own IBOV part is removed. Hedge per R$ 1 long is
> `hedge_ibov` in IBOV (BOVA11 or WIN as the tradable proxy) and `hedge_sector`
> in the sector index. No listed ETF tracks most B3 sector indices.

<DataTable data={risk_all} rows=100 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=asset_name title="Company"/>
  <Column id=ibov_weight title="IBOV Weight (%)" fmt=num2/>
  <Column id=sector_leg title="Sector Leg"/>
  <Column id=market_percent title="Market (%)" fmt=num1/>
  <Column id=sector_percent title="Sector (%)" fmt=num1/>
  <Column id=residual_percent title="Residual (%)" fmt=num1/>
  <Column id=ex_shock_residual_percent title="Residual ex-Shock (%)" fmt=num1/>
  <Column id=vol_total_percent title="Ann. Vol (%)" fmt=num1/>
  <Column id=beta_market title="Beta IBOV" fmt=num2/>
  <Column id=beta_sector title="Beta Sector" fmt=num2/>
  <Column id=hedge_ibov title="Hedge IBOV" fmt=num2/>
  <Column id=hedge_sector title="Hedge Sector" fmt=num2/>
  <Column id=flags title="Flags"/>
</DataTable>

---

## Not Decomposed

> Members with fewer than 120 joined returns (a recent listing) or a price
> series the endpoint refuses. The refusal text is the endpoint's own message.
> An empty table means every member was decomposed.

<DataTable data={risk_not_decomposed} rows=20>
  <Column id=ticker title="Ticker"/>
  <Column id=asset_name title="Company"/>
  <Column id=ibov_weight title="IBOV Weight (%)" fmt=num2/>
  <Column id=status title="Status"/>
  <Column id=n_returns title="Returns" fmt=num0/>
  <Column id=refusal title="Refusal"/>
</DataTable>
