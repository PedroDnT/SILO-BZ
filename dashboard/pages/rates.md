---
title: Rates and Curves
hide_title: true
sidebar_position: 3
---

<!--
  The B3 rates side of the pipeline, which had no page until now:

    b3_reference_rate      grain (curve, trade_date, calendar_days). B3 reference
                           curves from TaxaSwap.txt, daily from 2008-01-02. PRE =
                           DI x pré (nominal), DPL = clean IPCA coupon (real), DOC
                           = clean dollar coupon (not used here). 280 vertices per
                           curve per session: 60 FIXED (vertex_type F, nominal
                           tenor in calendar days in vertex_code) and 220 MOVING
                           (contract maturities).
    b3_futures_settlement  grain (trade_date, ticker). DI1 daily settlements from
                           2018-01-02. settlement_rate is the rate, settlement_price
                           the PU.

    bacen_expectativas     Focus survey, ExpectativasMercadoInflacao12Meses
                           (IPCA, next 12 months), joined on the curve session.
    cvm_fi_cda             CVM CDA fund portfolios, NTN-B rows of block
                           "Títulos Públicos" (repo collateral excluded).
    mkt_series             U.S. Treasury par curve, EIA Brent, OFR Financial
                           Stress Index. VIX is held but not published (Cboe
                           licence).

  METHOD: only B3's fixed vertices are read. PRE and DPL are both % a.a.
  compounded on 252 business days (api.curve_registry), and they publish the same
  fixed tenors every session, so breakeven = (1 + PRE) / (1 + DPL) - 1 at one
  vertex needs no interpolation. That is the implied inflation B3 describes in
  its curve manual. Breakeven is not shown below 1 year: DPL's short vertices
  lean on the current month's IPCA projection. Past the last DI1 / DAP maturity
  B3 extrapolates, so the long end is a model, not a price.

  ZERO-ROW RULE: every source is driven by a literal tenor list, a week spine or a
  one-row driver with the data LEFT JOINed on. Missing data renders blank.
-->

```sql rates_curve_latest
select * from supabase.rates_curve_latest
```

```sql rates_breakeven_latest
select * from supabase.rates_breakeven_latest
```

```sql rates_1y
select * from supabase.rates_breakeven_latest where tenor_label = '1y'
```

```sql rates_5y
select * from supabase.rates_breakeven_latest where tenor_label = '5y'
```

```sql rates_curve_long
select business_days, 'Nominal (PRE)' as curve, nominal_num2 as rate_num2 from supabase.rates_curve_latest
union all
select business_days, 'Real (DPL)' as curve, real_num2 as rate_num2 from supabase.rates_curve_latest
order by curve, business_days
```

```sql rates_history_long
select week, '1y' as tenor, real_1y_num2 as real_num2, breakeven_1y_num2 as breakeven_num2, nominal_1y_num2 as nominal_num2
from supabase.rates_history
union all
select week, '5y' as tenor, real_5y_num2, breakeven_5y_num2, nominal_5y_num2
from supabase.rates_history
order by tenor, week
```

```sql rates_di1_oi
select * from supabase.rates_di1_oi
```

```sql rates_focus_vs_breakeven
select week, 'Breakeven 1y (market)' as measure, breakeven_1y_num2 as value_num2
from supabase.rates_history
where week >= '2019-01-01'
union all
select week, 'Focus IPCA 12m (survey median)' as measure, focus_ipca_12m_num2 as value_num2
from supabase.rates_history
where week >= '2019-01-01'
order by measure, week
```

```sql rates_ntnb_fund_holdings
select * from supabase.rates_ntnb_fund_holdings
```

```sql rates_ntnb_by_maturity
select maturity_year, ntnb_bn, period
from supabase.rates_ntnb_holders_latest
where grain = 'maturity'
order by maturity_year
```

```sql rates_ntnb_top_funds
select fund, ntnb_bn, period
from supabase.rates_ntnb_holders_latest
where grain = 'fund'
order by ntnb_bn desc
```

```sql rates_global_latest
select * from supabase.rates_global_latest
```

```sql rates_global_history
select * from supabase.rates_global_history
```

```sql rates_ust_long
select week, 'UST 2y' as tenor, ust_2y_num2 as yield_num2 from supabase.rates_global_history
union all
select week, 'UST 10y' as tenor, ust_10y_num2 as yield_num2 from supabase.rates_global_history
order by tenor, week
```

# Rates and Curves

> The nominal and real yield curves B3 publishes every session, the inflation
> they imply, and where DI1 futures positions sit. Source: B3 reference rates
> (`b3_reference_rate`, daily since 2008-01-02) and the DI1 settlement report
> (`b3_futures_settlement`, daily since 2018-01-02). Each tile shows the session
> it comes from. Further down: the Focus survey against the market breakeven,
> how much NTN-B investment funds hold, and the global rates backdrop.
>
> **Breakeven is derived, not published as a series.** It is
> (1 + nominal) / (1 + real) - 1 at the same B3 fixed vertex, both rates in % a.a.
> on 252 business days. No interpolation, no smoothing. It includes any
> inflation risk premium, so it is not a forecast.

<BigValue data={rates_1y} value=real_num2 title="1y Real Yield (% a.a.)" fmt=num2/>
<BigValue data={rates_1y} value=breakeven_num2 title="1y Breakeven (%)" fmt=num2/>
<BigValue data={rates_5y} value=real_num2 title="5y Real Yield (% a.a.)" fmt=num2/>
<BigValue data={rates_5y} value=breakeven_num2 title="5y Breakeven (%)" fmt=num2/>
<BigValue data={rates_1y} value=trade_date title="Session"/>

---

## Latest Curves

> PRE (DI x pré, nominal) and DPL (IPCA coupon, real) on B3's fixed vertices, by
> business days to the vertex. Daily, updated by the morning ingest run. DPL's
> first months move with the current month's IPCA projection, not with real rates.
> Past the last DI1 and DAP maturities B3 extrapolates the last forward rate.

<LineChart
  data={rates_curve_long}
  x=business_days
  y=rate_num2
  series=curve
  xAxisTitle="Business days"
  yAxisTitle="% a.a."
  title="Nominal (PRE) and Real (DPL) Curves, Latest Session"
/>

<LineChart
  data={rates_curve_latest}
  x=business_days
  y=breakeven_num2
  xAxisTitle="Business days"
  yAxisTitle="%"
  title="Implied Breakeven Inflation by Tenor, 1 Year and Longer"
/>

<DataTable data={rates_breakeven_latest} rows=4>
  <Column id=tenor_label title="Tenor"/>
  <Column id=tenor_days title="Vertex (Calendar Days)"/>
  <Column id=business_days title="Business Days"/>
  <Column id=nominal_num2 title="Nominal (% a.a.)" fmt=num2/>
  <Column id=real_num2 title="Real (% a.a.)" fmt=num2/>
  <Column id=breakeven_num2 title="Breakeven (%)" fmt=num2/>
  <Column id=trade_date title="Session"/>
</DataTable>

---

## Real Yields and Breakevens Since 2008

> Weekly: the last session of each week, at B3's fixed 360-day and 1,800-day
> vertices. A week with no session is blank. Same method as above.

<LineChart
  data={rates_history_long}
  x=week
  y=real_num2
  series=tenor
  yAxisTitle="% a.a."
  title="1y and 5y Real Yield (DPL)"
/>

<LineChart
  data={rates_history_long}
  x=week
  y=breakeven_num2
  series=tenor
  yAxisTitle="%"
  title="1y and 5y Implied Breakeven Inflation"
/>

<LineChart
  data={rates_history_long}
  x=week
  y=nominal_num2
  series=tenor
  yAxisTitle="% a.a."
  title="1y and 5y Nominal Yield (PRE)"
/>

### Market Breakeven vs the Focus Survey

> The 1-year breakeven above against the BACEN Focus survey's median forecast
> for IPCA over the next 12 months (`bacen_expectativas`, unsmoothed series),
> read on the same session; weeks with no Focus row that day are blank. Focus
> starts 2019-01. The two are not the same quantity: the breakeven is a market
> price and also carries an inflation risk premium, so a gap between them is
> not a forecast error.

<LineChart
  data={rates_focus_vs_breakeven}
  x=week
  y=value_num2
  series=measure
  yAxisTitle="%"
  title="1y Breakeven vs Focus 12-Month IPCA Median"
/>

---

## DI1 Open Interest by Maturity

> Contracts open per DI1 maturity on the latest session, from B3's daily
> settlement report. The rate is B3's settlement rate (% a.a., 252 business days).
> A contract expires on its month's first business day. Context for where the
> nominal curve is anchored: the PRE curve past the last listed DI1 is extrapolated.

<BarChart
  data={rates_di1_oi}
  x=maturity_month
  y=open_interest
  yAxisTitle="Contracts"
  title="DI1 Open Interest by Maturity, Latest Session"
/>

<DataTable data={rates_di1_oi} rows=15>
  <Column id=ticker title="Contract"/>
  <Column id=maturity_month title="Maturity Month"/>
  <Column id=open_interest title="Open Interest" fmt=num0/>
  <Column id=contracts title="Traded" fmt=num0/>
  <Column id=settlement_rate_num2 title="Settlement Rate (% a.a.)" fmt=num2/>
  <Column id=trade_date title="Session"/>
</DataTable>

---

## Who Holds NTN-Bs: Investment Funds

> NTN-B (Tesouro IPCA+) positions reported by Brazilian investment funds in
> CVM's monthly portfolio filing (CDA, `cvm_fi_cda`, block "Títulos Públicos"),
> at the market value each fund reported. Repo collateral is excluded: it is a
> loan backed by NTN-Bs, not a holding. Funds only: banks, insurers, pension
> plans held directly and foreign investors are not in this filing.
>
> **The series stops at the last complete month.** CVM's newest CDA months are
> partly filed: from 2026-06 they hold about 60% of the usual funds. The chart
> ends at the last month with at least 90% of the prior year's median count of
> holding funds, shown in the Month column below. Monthly, last 36 months.

<LineChart
  data={rates_ntnb_fund_holdings}
  x=period
  y=ntnb_bn
  yAxisTitle="R$bn"
  title="NTN-B Held by Investment Funds (R$bn, CVM CDA)"
/>

<BarChart
  data={rates_ntnb_by_maturity}
  x=maturity_year
  y=ntnb_bn
  yAxisTitle="R$bn"
  title="NTN-B Held by Funds, by Maturity Year (R$bn, latest complete month)"
/>

<DataTable data={rates_ntnb_top_funds} rows=15>
  <Column id=fund title="Fund"/>
  <Column id=ntnb_bn title="NTN-B Held (R$bn)" fmt=num2/>
  <Column id=period title="Month"/>
</DataTable>

---

## Global Backdrop

> The rates a Brazilian curve is read against, each from its primary publisher
> (`mkt_series`): the U.S. Treasury par yield curve (% a.a.), Brent spot from
> the EIA (USD per barrel, published weekly) and the OFR Financial Stress Index
> (above zero means stress above its average; published about two business
> days late). Weekly history takes each series' last observation in the week.
> VIX is not shown: Cboe requires a licence to publish it, so the OFR index
> stands in as the stress gauge.

<LineChart
  data={rates_global_latest}
  x=tenor_years
  y=ust_par_num2
  xAxisTitle="Years"
  yAxisTitle="% a.a."
  title="US Treasury Par Curve, Latest Day"
/>

<LineChart
  data={rates_ust_long}
  x=week
  y=yield_num2
  series=tenor
  yAxisTitle="% a.a."
  title="US Treasury 2y and 10y Par Yields"
/>

<LineChart
  data={rates_global_history}
  x=week
  y=brent_usd_num2
  yAxisTitle="USD per barrel"
  title="Brent Spot (EIA)"
/>

<LineChart
  data={rates_global_history}
  x=week
  y=ofr_fsi_num2
  yAxisTitle="Index"
  title="OFR Financial Stress Index"
/>
