---
title: Follow the Money
hide_title: true
sidebar_position: 5
---

<!--
  Investor-type flow on B3 (b3_investor_participation via
  fact_investor_flow_daily) plus the ADTV series from our own tape.

  THE DERIVATION, and why it is not a stored column. B3 does not publish a
  daily net flow. It publishes a MONTH-TO-DATE CUMULATIVE snapshot of buys and
  sells per investor type, refreshed each session and lagged T+2 (the export
  requested on 2026-09-10 is captioned "até o dia 08/09/2026"). A day's flow is
  the first difference of consecutive snapshots WITHIN a month.

  Two ways that goes wrong, both handled in fact_investor_flow_daily rather
  than here:
    * Differencing ACROSS a month boundary would report a whole month as one
      day's outflow. The LAG is partitioned by month.
    * The first snapshot SILO holds for a month is not necessarily the month's
      first session — on the day this pipeline was deployed it was mid-month.
      Treating that MTD total as one day would invent a spike on an arbitrary
      date, so those rows carry NULL and flow_basis='unknown_opening_snapshot',
      and this page drops them rather than charting a zero.

  WHY THERE IS NO YTD OR 12-MONTH COLUMN. B3 keeps ~21 business days of this
  table and publishes no archive. A "YTD" computed over the fortnight we hold
  would be a YTD number in name only. The summary table shows last day, one
  week, month-to-date and coverage-to-date, with the coverage window printed
  beside it.

  THE ADTV CHART IS DIFFERENT. It comes from b3_cotahist (via
  mv_b3_monthly_activity), not from B3's AverageChart export, because
  AverageChart only ever returns a trailing 12 months while our tape goes back
  to 2019. The two agree where they overlap.

  INTERNAL CHECK worth knowing: net flow summed across ALL investor types must
  be ~0 for any window, because every purchase is someone's sale. It is (to
  rounding) — that is the cheapest available proof the differencing is right.

  ZERO-ROW SAFETY: headline is aggregate-single-row; the series return zero
  rows on a fresh database and render as empty charts.
-->

```sql headline
select * from supabase.flow_headline
```

```sql flow_daily
select * from supabase.flow_daily
```

```sql flow_summary
select * from supabase.flow_summary
```

```sql monthly_market
select * from supabase.flow_monthly_market
```

```sql adtv
select * from supabase.flow_adtv_monthly
```

```sql flow_main
select reference_date, investor_type, net_acum_brl_bn, net_brl_bn
from supabase.flow_daily
where investor_type in ('Investidor Estrangeiro','Institucionais','Investidores Individuais')
order by reference_date
```

```sql monthly_vista
select reference_month, investor_type, valor_brl_bn, participacao
from supabase.flow_monthly_market
where market = 'À vista'
order by reference_month desc, valor_brl_bn desc
```

# Follow the Money — Fluxos B3 & ANBIMA

> Who is buying and who is selling on B3, by investor type, and how much the
> exchange trades in aggregate. The flow is **derived**: B3 publishes a
> month-to-date cumulative snapshot, not a daily number, so what you see is the
> first difference of consecutive snapshots within each month.
>
> **B3 publishes this with a T+2 lag.** The most recent flow date is two
> sessions behind today's tape. A flow series that stops two days short of the
> price series is the feed working correctly, not stalling.
>
> **Coverage is short and cannot be backfilled.** B3 retains roughly 21 business
> days of the participation table. That is why there is no year-to-date column
> below: a YTD computed over a fortnight would be a YTD in name only.

{#if headline[0].reference_date}

<BigValue data={headline} value=reference_date title="Latest Flow Date"/>
<BigValue data={headline} value=publication_lag_days title="Lag vs Tape (days)" fmt=num0/>
<BigValue data={headline} value=estrangeiro_last_day_bn title="Estrangeiro — Last Day (R$bn)" fmt=num2/>
<BigValue data={headline} value=sessions_held title="Sessions Captured" fmt=num0/>

{:else}

<Alert status=warning>
**No investor-flow sessions captured yet.** B3 retains roughly 21 business days
of the participation table and publishes no archive, so this page begins at
SILO's first daily capture. Nothing is missing that can be recovered — the first
`run_daily` after deploy fills it.
</Alert>

{/if}

---

## Fluxo Líquido Acumulado por Tipo de Investidor

> Cumulative net flow over the window SILO holds, in R$ bn. This accumulates
> from the **start of coverage**, not from the start of the year — see the lede.
> Foreign and institutional are usually near mirror images of each other; that
> is arithmetic, not a signal, since every purchase is someone's sale.

{#if flow_main.length > 0}

<LineChart
  data={flow_main}
  x=reference_date
  y=net_acum_brl_bn
  series=investor_type
  yAxisTitle="Fluxo Acumulado (R$ bn)"
  title="Cumulative Net Flow by Investor Type (R$ bn)"
/>

{:else}

<Alert status=warning>
**No investor-flow sessions captured yet.** B3 retains roughly 21 business days
of the participation table and publishes no archive, so this page begins at
SILO's first daily capture. Nothing is missing that can be recovered — the first
`run_daily` after deploy fills it.
</Alert>

{/if}

## Fluxo Líquido Diário

> The per-session net, before accumulation. Sessions whose flow could not be
> derived honestly — the first snapshot held in a month, when that is not the
> month's first session — are omitted rather than drawn as zero.

{#if flow_main.length > 0}

<BarChart
  data={flow_main}
  x=reference_date
  y=net_brl_bn
  series=investor_type
  type=grouped
  yAxisTitle="Fluxo Líquido (R$ bn)"
  title="Daily Net Flow by Investor Type (R$ bn)"
/>

{:else}

<Alert status=warning>
**No investor-flow sessions captured yet.** B3 retains roughly 21 business days
of the participation table and publishes no archive, so this page begins at
SILO's first daily capture. Nothing is missing that can be recovered — the first
`run_daily` after deploy fills it.
</Alert>

{/if}

## Resumo por Janela

> `Coverage` is the sum over everything captured, with the window that produced
> it printed beside it — the honest replacement for a year-to-date column on a
> feed that keeps three weeks.

{#if flow_summary[0].last_date}

<DataTable data={flow_summary}>
  <Column id=investor_type title="Categoria"/>
  <Column id=last_day_bn title="Last Day" fmt=num2 contentType=colorscale scaleColor=green/>
  <Column id=week_bn title="1 Week" fmt=num2 contentType=colorscale scaleColor=green/>
  <Column id=mtd_bn title="MTD" fmt=num2 contentType=colorscale scaleColor=green/>
  <Column id=coverage_bn title="Coverage" fmt=num2 contentType=colorscale scaleColor=green/>
  <Column id=coverage_from title="Desde"/>
  <Column id=coverage_to title="Até"/>
</DataTable>

{:else}

<Alert status=warning>
**No investor-flow sessions captured yet.** B3 retains roughly 21 business days
of the participation table and publishes no archive, so this page begins at
SILO's first daily capture. Nothing is missing that can be recovered — the first
`run_daily` after deploy fills it.
</Alert>

{/if}

---

## ADTV Mensal — B3

> Average daily traded value on the cash market, computed from our own COTAHIST
> tape rather than from B3's rolling 12-month summary, so the history goes back
> as far as the tape does. Months are complete by construction the day B3
> publishes each session file — a month that dips is a month with fewer
> sessions ingested, which `Sessões` makes visible.

<LineChart
  data={adtv}
  x=month
  y=adtv_brl_bn
  yAxisTitle="ADTV (R$ bn)"
  title="B3 Cash Market — Average Daily Traded Value (R$ bn)"
/>

## Participação Mensal por Tipo de Investidor — Mercado à Vista

> B3's own published monthly aggregate (buys + sells), not a derivation, so this
> one carries no basis caveat. It is still forward-only: past months return no
> rows at the source, so the history grows one month per run.

{#if monthly_vista.length > 0}

<DataTable data={monthly_vista} groupBy=reference_month>
  <Column id=investor_type title="Categoria"/>
  <Column id=valor_brl_bn title="Volume (R$ bn)" fmt=num1/>
  <Column id=participacao title="Participação" fmt='0.0"%"'/>
</DataTable>

{:else}

<Alert status=warning>
**No monthly participation published yet for the window we hold.** B3 returns no
rows for past months at the source, so this table grows one month per run.
</Alert>

{/if}

---

## Fluxos ANBIMA

> The fund-industry side of the same question — net subscriptions and
> redemptions by ANBIMA class — lives on [Industry](/industry), sourced from
> `anbima_class_monthly`. Unlike everything above it, that series has full
> history: ANBIMA publishes an archive, B3 does not.
