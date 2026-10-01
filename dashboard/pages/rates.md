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

# Rates and Curves

> The nominal and real yield curves B3 publishes every session, the inflation
> they imply, and where DI1 futures positions sit. Source: B3 reference rates
> (`b3_reference_rate`, daily since 2008-01-02) and the DI1 settlement report
> (`b3_futures_settlement`, daily since 2018-01-02). Each tile shows the session
> it comes from.
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
