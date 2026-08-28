---
title: Macro Context
---

<!--
  The BACEN side of the pipeline, which until now had ZERO consumers: three
  tables ingested every day by src/pipeline/bacen_pipeline.py and read by
  nothing.

    bacen_sgs           grain (series_code, reference_date) — 10 configured SGS
                        series (SGS_SERIES in bacen_pipeline.py)
    bacen_ptax          grain (currency, reference_date) — USD/EUR/GBP/JPY/ARS,
                        buy_rate + sell_rate
    bacen_expectativas  grain (endpoint_name, indicador, reference_date,
                        horizon) — Focus survey median / mean / std_dev.
                        horizon is DataReferencia (year for Anuais, month/year
                        for Mensais). Fetch filters to baseCalculo=0 (30-day
                        window) and, on the Inflacao12/13-24 endpoints,
                        Suavizada='N'. Those two dimensions are NOT in the
                        unique key: a filter regression would silently collide
                        again. Historical months older than the daily window
                        stay sparse until a bacen_only backfill is dispatched
                        (docs/DATABASE_MAINTENANCE.md §4).

  UNITS ARE BACEN'S AND ARE NOT CONVERTED. They differ per series and mixing
  them would be the fastest way to publish a wrong number:
    432  SELIC meta          % a.a.   (annualised policy target)
    11   SELIC diária        % a.d.   (daily rate — NOT comparable to 432)
    12   CDI                 % a.d.
    433  IPCA / 189 IGP-M / 188 INPC / 25 poupança   % change in the month
    1    USDBRL              BRL per USD
    4380 PIB                 R$ million, monthly, current prices
  The unit travels with the row in the series inventory table so the reader can
  always check which one they are looking at.

  FOCUS CAVEAT, stated on the page as well: bacen_expectativas is keyed UNIQUE on
  (endpoint_name, indicador, reference_date, horizon) since migration 16. The
  series query pins horizon = the survey's calendar year so adjacent points are
  the same forecast, not a mix of 1y and 5y. Rows ingested before that migration
  (and not yet re-fetched) can still lack extra horizons — the 24-month chart
  then renders blank for those months rather than a mixed track. baseCalculo and
  Suavizada are fetch-time filters, not key columns.

  ZERO-ROW RULE: every source here is driven from a generate_series spine or a
  literal driver list with the data LEFT JOINed on, so no source can return zero
  rows. A 0-row source makes Evidence write a zero-byte parquet and the whole
  build then dies with "Invalid Input Error: File ... too small to be a Parquet
  file". Missing data renders blank; nothing is filled in.

  FORMATTING NOTE: series_code carries NO numeric fmt. It is an identifier, and
  num0 renders SGS 4380 as "4,380".
-->

```sql macro_latest
select * from supabase.macro_latest
```

```sql macro_rate_series
select * from supabase.macro_rate_series
```

```sql macro_fx_series
select * from supabase.macro_fx_series
```

```sql macro_fx_latest
select * from supabase.macro_fx_latest
```

```sql macro_focus_series
select * from supabase.macro_focus_series
```

```sql macro_focus_latest
select * from supabase.macro_focus_latest
```

```sql macro_series_inventory
select * from supabase.macro_series_inventory
```

# Macro Context

> The discount rate, the currency and the expectations every fund on this site is
> implicitly measured against — straight from `bacen_sgs`, `bacen_ptax` and
> `bacen_expectativas`. When SELIC sits high, a fixed-income fund clearing CDI is
> doing nothing remarkable, and a credit book's delinquency has a macro
> explanation as readily as a governance one.
>
> **Units are BACEN's and are not converted.** SELIC meta is annualised (% a.a.)
> while SELIC diária and CDI are per-day (% a.d.); the inflation series are
> month-on-month, not twelve-month accumulations. Nothing on this page has been
> annualised, chained or rebased, because each of those is an assumption rather
> than data. The unit travels with every row in the inventory table at the bottom.

<BigValue data={macro_latest} value=selic_meta_num2 label="SELIC Target (% a.a.)" fmt=num2/>
<BigValue data={macro_latest} value=ipca_mes_num2 label="IPCA (% in Month)" fmt=num2/>
<BigValue data={macro_latest} value=usd_brl label="USD/BRL (PTAX Sell)" fmt=num2/>
<BigValue data={macro_latest} value=focus_ipca_median_num2 label="Focus IPCA Median (%)" fmt=num2/>
<BigValue data={macro_latest} value=sgs_through label="SGS Data Through"/>

---

## Policy Rate

> SELIC meta is the annualised policy target (% a.a.). The daily SELIC and CDI
> series below it are **% per day** — they are not on the same scale and are
> deliberately not converted, because an annualisation convention is an
> assumption, not data.

<LineChart
  data={macro_rate_series}
  x=period
  y=selic_meta_num2
  yAxisTitle="% a.a."
  title="SELIC Target — Last 60 Months"
/>

<LineChart
data={macro_rate_series}
x=period
y={['selic_diaria_num2','cdi_num2']}
yAxisTitle="% a.d."
title="SELIC Diária vs CDI (% per Day)"
/>

---

## Inflation

> Each series is the **change in that month**, not a 12-month accumulation. Blank
> months are months BACEN has not published (or has not been ingested), never
> zero.

<LineChart
data={macro_rate_series}
x=period
y={['ipca_mes_num2','igpm_mes_num2','inpc_mes_num2','poupanca_mes_num2']}
yAxisTitle="% Change in Month"
title="IPCA · IGP-M · INPC · Poupança"
/>

---

## Exchange Rates

> PTAX month-end **sell** rate, BRL per unit of foreign currency. USD, EUR and
> GBP are charted together because they share a scale; JPY and ARS are orders of
> magnitude smaller and would flatten to zero on the same axis, so they appear in
> the table below instead.

<LineChart
data={macro_fx_series}
x=period
y={['usd_brl','eur_brl','gbp_brl']}
yAxisTitle="BRL per Unit"
title="PTAX Month-End — USD, EUR, GBP"
/>

> Bid-ask spread below: `spread_num2` = (sell − buy) / sell, in percentage points.
> All five configured currencies are listed whether or not they have data, so a
> currency that failed to ingest is visible as a blank line rather than silently
> absent.

<DataTable data={macro_fx_latest}>
  <Column id=currency title="Currency"/>
  <Column id=reference_date title="Latest Quote"/>
  <Column id=buy_rate title="Buy (BRL)" fmt='#,##0.00'/>
  <Column id=sell_rate title="Sell (BRL)" fmt='#,##0.00'/>
  <Column id=spread_num2 title="Spread (%)" fmt=num2/>
  <Column id=days_stale title="Days Stale" fmt=num0/>
  <Column id=n_obs title="Observations" fmt=num0/>
</DataTable>

---

## Focus Consensus

> Median forecast from the Focus bulletin (`ExpectativasMercadoAnuais`), one
> reading per month — the **last survey published in that month**, not an average
> of the month's surveys.
>
> Each point is the last survey in that month for the **current-calendar-year
> horizon** (`horizon = YYYY` of the survey date), so adjacent months are the
> same forecast, not a mix of 1-year and 5-year numbers. Months that were never
> re-fetched after the horizon key landed render blank — a coverage gap, not a
> blended vintage. The horizon that actually landed is shown per row in the
> latest-reading table below.
>
> **Every January the line steps** — that is the forecast _target_ rolling
> over (December plots the forecast for the year just ending, January the
> forecast for the new year), not a revision and not a data error. Selic is
> the clearest case: the December point is effectively the realized year-end
> rate, the January point a fresh year-ahead forecast.

<LineChart
  data={macro_focus_series}
  x=period
  y=median_val
  series=indicador
  yAxisTitle="Median Forecast (%)"
  title="Focus Median by Indicator — Last 24 Months"
/>

> Dispersion below is the standard deviation across forecasters for the same
> readings. Rising dispersion means the market disagrees more, which is
> information the median alone hides. Blank months are the same coverage gap as
> the median chart (pre-horizon-key rows not yet re-fetched), not a mixed
> horizon.

<LineChart
  data={macro_focus_series}
  x=period
  y=std_dev
  series=indicador
  yAxisTitle="Std. Deviation"
  title="Focus Forecast Dispersion by Indicator"
/>

---

## Latest Focus Reading per Endpoint

> Every (endpoint, indicator) pair the pipeline subscribes to. `Horizon` is
> `raw->>'DataReferencia'` — the period the forecast is _about_; `Survey Date` is
> when it was collected.

<DataTable data={macro_focus_latest} rows=10>
  <Column id=endpoint_name title="Endpoint"/>
  <Column id=indicador title="Indicator"/>
  <Column id=horizon title="Horizon"/>
  <Column id=survey_date title="Survey Date"/>
  <Column id=median_val title="Median" fmt=num2/>
  <Column id=mean_val title="Mean" fmt=num2/>
  <Column id=std_dev title="Std Dev" fmt=num2/>
  <Column id=days_stale title="Days Stale" fmt=num0/>
  <Column id=n_obs title="Rows Stored" fmt=num0/>
</DataTable>

---

## SGS Series Coverage

> All ten series the ingestor is configured to fetch, each with its own unit.
> This is the honest inventory: a series with no observations shows blank counts
> rather than being dropped from the list. `Last Value` is in the unit named on
> its own row and the column must not be read down the page.

<DataTable data={macro_series_inventory} rows=10>
  <Column id=series_code title="SGS Code"/>
  <Column id=series_name title="Series"/>
  <Column id=unit title="Unit (as published)"/>
  <Column id=n_obs title="Observations" fmt=num0/>
  <Column id=first_obs title="First"/>
  <Column id=last_obs title="Last"/>
  <Column id=last_value title="Last Value" fmt=num2/>
  <Column id=days_stale title="Days Stale" fmt=num0/>
</DataTable>

> Ingest health for these tables — when BACEN last landed, and whether the run
> succeeded — is on [Pipeline Ops](/ops).
