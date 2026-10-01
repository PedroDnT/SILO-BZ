---
title: Macro Context
hide_title: true
sidebar_position: 2
---

<!--
  BACEN side: bacen_sgs (35 SGS series incl. the 25-code IPCA set, api.inflation),
  ibge_ipca_item_monthly (IPCA tree with weights, api.inflation_items), bacen_ptax,
  bacen_expectativas (Focus; baseCalculo=0 and Suavizada='N' are fetch-time filters,
  not key columns; the series query pins horizon = survey calendar year).
  Units are BACEN's and NOT converted (432 % a.a.; 11 and 12 % a.d.; 433/189/188/25 %
  in month; 1 BRL per USD; 4380 R$ million; 13522 12-month %; 21379 diffusion).
  IBGE group codes are not in IBGE's order: 1640 Comunicação, 1641 Saúde, 1642 Despesas
  pessoais, 1643 Educação (value-matched against SIDRA).
  Zero-row rule: every source is a spine LEFT JOINed with data, because a 0-row source
  breaks the Evidence build. series_code carries no numeric fmt (num0 shows 4,380).
-->

```sql macro_latest
select * from supabase.macro_latest
```

```sql macro_rate_series
select * from supabase.macro_rate_series
```

```sql cpi_series
-- The monthly indices publish month M during M+1, so the source's last ended
-- month is usually still empty for them. Stop this chart at its own last month
-- with a reading; the SELIC/CDI charts keep the full spine (daily-carried).
select *
from supabase.macro_rate_series
where period <= (
  select max(period)
  from supabase.macro_rate_series
  where ipca_mes_num2 is not null
     or igpm_mes_num2 is not null
     or inpc_mes_num2 is not null
     or poupanca_mes_num2 is not null
)
order by period
```

```sql inflation_series
-- Same clamp as cpi_series: stop at the last month with a headline reading,
-- so the chart does not draw the unpublished trailing month as a gap.
select *
from supabase.macro_inflation_series
where period <= (
  select max(period)
  from supabase.macro_inflation_series
  where ipca_mes_num2 is not null
)
order by period
```

```sql inflation_groups_latest
select * from supabase.macro_inflation_groups_latest
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

> The rate, currency and expectations every fund here is measured against, from `bacen_sgs`, `bacen_ptax` and `bacen_expectativas` (BACEN). **Units are BACEN's and not converted**: SELIC meta is % a.a., SELIC diária and CDI are % a.d., inflation is month-on-month; the unit is on every inventory row.

<BigValue data={macro_latest} value=selic_meta_num2 title="SELIC Target (% a.a.)" fmt=num2/>
<BigValue data={macro_latest} value=ipca_mes_num2 title="IPCA (% in Month)" fmt=num2/>
<BigValue data={macro_latest} value=usd_brl title="USD/BRL (PTAX Sell)" fmt=num2/>
<BigValue data={macro_latest} value=focus_ipca_median_num2 title="Focus IPCA Median (%)" fmt=num2/>
<BigValue data={macro_latest} value=sgs_through title="SGS Data Through"/>

---

## Policy Rate

> SELIC meta is % a.a.; daily SELIC and CDI are **% per day**, deliberately not converted (BACEN SGS, daily series).

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

> Each series is the **change in that month**, not a 12-month accumulation (BACEN SGS, monthly, published in M+1). Blank means unpublished or not ingested, never zero.

<LineChart
data={cpi_series}
x=period
y={['ipca_mes_num2','igpm_mes_num2','inpc_mes_num2','poupanca_mes_num2']}
yAxisTitle="% Change in Month"
title="IPCA · IGP-M · INPC · Poupança"
/>

### Inside the IPCA

> Headline against the three BCB cores (EX0, MS smoothed trimmed mean, DP double-weighted), from `bacen_sgs` via `api.inflation` (monthly, M+1). Lines are the **change in that month**; the 12-month line is BACEN's own accumulation (SGS 13522), not chained here.

<LineChart
data={inflation_series}
x=period
y={['ipca_mes_num2','core_ex0_num2','core_ms_num2','core_dp_num2']}
yAxisTitle="% Change in Month"
title="IPCA Headline vs BCB Cores — Last 36 Months"
/>

<LineChart
  data={inflation_series}
  x=period
  y=ipca_12m_num2
  yAxisTitle="% Accumulated 12 Months"
  title="IPCA — 12-Month Accumulation (BACEN 13522)"
/>

> Monitored prices move on regulatory calendars; free prices are demand-sensitive.

<LineChart
data={inflation_series}
x=period
y={['monitorados_num2','livres_num2']}
yAxisTitle="% Change in Month"
title="Monitored vs Free Prices (% per Month)"
/>

### What Moved the IPCA

> IBGE's nine groups for the latest month held, from `ibge_ipca_item_monthly` (SIDRA 7060, monthly, M+1) via `api.inflation_items`. **Contribution = weight × change ÷ 100**, in p.p. of the headline and the one derived number here; the bars sum to the month's IPCA to rounding. Weights are IBGE's.

<BarChart
  data={inflation_groups_latest}
  x=group_name
  y=contribution_num2
  swapXY=true
  yAxisTitle="p.p. of headline"
  title="Contribution to the Month's IPCA by Group"
/>

<DataTable data={inflation_groups_latest} rows=9>
  <Column id=group_name title="Group"/>
  <Column id=reference_month title="Month"/>
  <Column id=weight_num2 title="Weight (%)" fmt=num2/>
  <Column id=change_month_num2 title="Change in Month (%)" fmt=num2/>
  <Column id=contribution_num2 title="Contribution (p.p.)" fmt=num2/>
  <Column id=change_12m_num2 title="12-Month (%)" fmt=num2/>
</DataTable>

---

## Exchange Rates

> PTAX month-end **sell** rate, BRL per unit (BACEN, daily). JPY and ARS are orders of magnitude smaller and appear in the table instead.

<LineChart
data={macro_fx_series}
x=period
y={['usd_brl','eur_brl','gbp_brl']}
yAxisTitle="BRL per Unit"
title="PTAX Month-End — USD, EUR, GBP"
/>

> `spread_num2` = (sell − buy) / sell, in p.p. All five currencies are listed even without data, so a failed ingest shows blank.

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

> Median from the Focus bulletin (`ExpectativasMercadoAnuais`, BACEN): the **last survey in each month**, at the **current-calendar-year horizon**, so adjacent points are the same forecast. Months never re-fetched after the horizon key landed render blank, a coverage gap not a blended vintage. **Every January the line steps** because the forecast target rolls over, not a revision or error.

<LineChart
  data={macro_focus_series}
  x=period
  y=median_val
  series=indicador
  yAxisTitle="Median Forecast (%)"
  title="Focus Median by Indicator — Last 24 Months"
/>

> Standard deviation across forecasters for the same readings; blanks are the same coverage gap.

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

> Every pair the pipeline subscribes to. `Horizon` is the period the forecast is about; `Survey Date` is when it was collected.

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

> All 35 configured series, each with its own unit; a series with no observations shows blank counts. `Last Value` is in the unit on its own row: do not read the column down the page.

<DataTable data={macro_series_inventory} rows=35>
  <Column id=series_code title="SGS Code"/>
  <Column id=series_name title="Series"/>
  <Column id=unit title="Unit (as published)"/>
  <Column id=n_obs title="Observations" fmt=num0/>
  <Column id=first_obs title="First"/>
  <Column id=last_obs title="Last"/>
  <Column id=last_value title="Last Value" fmt=num2/>
  <Column id=days_stale title="Days Stale" fmt=num0/>
</DataTable>

> Ingest health is on [Pipeline Ops](/ops).
