---
title: Pipeline Ops
---

<!--
  The operator view: did the pipeline run, did it succeed, and did the data
  actually land. This page exists because a month-long silent outage is only
  silent when nobody is looking at cvm_ingest_log.

  SOURCES
    cvm_ingest_log        one row per ingest run (grain run_id). Written by
                          src/pipeline/cvm_pipeline.py::_log_start/_log_finish
                          and by the ANBIMA ETF pipeline.
    ingest_log_summary()  09_analytical_functions.sql — per (entity, doc_type)
                          run counts over a window.
    data_coverage()       09_analytical_functions.sql — distinct funds per
                          (period, entity_type) in fact_fund_monthly.
    plus the base tables themselves, read directly for their newest row.

  STATUS VOCABULARY (from _log_finish, and it matters):
    ok       the slice was fetched and upserted.
    skipped  the month is not published yet — CVM 404s and the run is recorded
             skipped ON PURPOSE, so it is not a false alarm. Deep history is
             run_backfill's job, not the daily window's.
    error    a real failure, INCLUDING the "fetched N rows but upserted 0" case:
             a source file that parsed to nothing is a defect, not a no-op. That
             exact rule is what stopped cvm_fiagro_mensal sitting empty behind 34
             'ok' slices.
    running  started and never reached a terminal status — a process that died.

  WHY BOTH HALVES ARE HERE: the log records what the pipeline THINKS it did; the
  table-freshness section reads the tables themselves. A recent 'ok' over a table
  whose newest row is months old is the disagreement worth catching, and only
  showing both makes it visible. SECTION ORDER follows that argument: the log
  first (did it run, did it succeed, per entity, per dataset), then the tables
  themselves, then the analytical layer downstream of both.

  ENTITY LABELS are the ones the pipeline actually writes to the log
  (fi / fidc / fiagro / fii / fip / securit / etf / cia_aberta / anbima_etf), NOT
  the API dispatch keys — the two differ (the log says doc_type 'inf_diario'
  where the old Flask dispatch called it 'diario'; ingest is CLI/Actions now).

  ZERO-ROW RULE: day spines, month spines, slot spines and literal entity lists
  drive every source, with the log LEFT JOINed on. An empty log yields blank rows
  rather than a 0-row source — which writes a zero-byte parquet and kills the
  Evidence build. This page has to survive exactly the scenario it reports on.

  FORMATTING NOTE: year columns carry NO numeric fmt. num0 renders 2026 as
  "2,026".
-->

```sql ops_health
select * from supabase.ops_health
```

```sql ops_daily_rows
select * from supabase.ops_daily_rows
```

```sql ops_freshness
select * from supabase.ops_freshness
```

```sql ops_status_by_dataset
select * from supabase.ops_status_by_dataset
```

```sql ops_table_freshness
select * from supabase.ops_table_freshness
```

```sql ops_coverage
select * from supabase.ops_coverage
```

```sql ops_recent_runs
select * from supabase.ops_recent_runs
```

# Pipeline Ops

> Every ingest run writes exactly one `cvm_ingest_log` row, so this page is the
> audit trail — and the answer to "has anything quietly stopped landing". Read it
> before quoting any number on this site as current: a page that renders perfectly
> from three-month-old data looks exactly like a page that renders from today's.
>
> The failure this page is built to catch is **not** the loud one. A run that
> errors is visible everywhere; a cron that never fires logs nothing at all, and a
> slice that reports `ok` while its table stops advancing looks healthy in the log.
> That is why the log and the tables themselves are both shown, and why a
> disagreement between them is the thing to look for.

<BigValue data={ops_health} value=hours_since_last_run label="Hours Since Last Run" fmt=num1/>
<BigValue data={ops_health} value=runs_24h label="Runs (24h)" fmt=num0/>
<BigValue data={ops_health} value=errors_7d label="Errors (7d)" fmt=num0/>
<BigValue data={ops_health} value=stuck_running label="Stuck 'running'" fmt=num0/>
<BigValue data={ops_health} value=rows_7d label="Rows Upserted (7d)" fmt=num0/>

> **How to read the health strip.** The cron runs daily at 06:00 UTC, so
> `Hours Since Last Run` above ~30 means the schedule itself has stopped — the
> failure mode that produces a silent outage, because a pipeline that never runs
> logs no errors at all. `Stuck 'running'` counts runs that began more than six
> hours ago and never wrote a terminal status: a process that died mid-run.
> `Errors (7d)` includes slices that fetched rows but upserted none.

---

## Rows Ingested per Day

> Last 30 days, one bar per calendar day. **A day with no bar is a day the
> pipeline did not run** — the day spine keeps empty days on the axis instead of
> dropping them, which is precisely what makes an outage visible rather than
> invisible.

<BarChart
  data={ops_daily_rows}
  x=day
  y=rows_upserted
  yAxisTitle="Rows Upserted"
  title="Rows Upserted per Day — Last 30 Days"
/>

> The same 30 days by outcome below. `skipped` is expected and healthy — it is how
> a month CVM has not published yet is recorded. `error` and `running` are not.

<BarChart
data={ops_daily_rows}
x=day
y={['n_ok','n_skipped','n_error','n_running']}
type=stacked
yAxisTitle="Runs"
title="Run Status per Day"
/>

---

## Freshness — Last Successful Slice per Entity

> Sorted worst-first. `Days Since OK` counts only **successful** runs, because a
> 404 (`skipped`) and a failure (`error`) both mean no data arrived.
>
> The tell for a silent outage is the pair of columns on the right: a stale
> `Last OK` next to a recent `Last Attempt` whose status is not `ok`. An entity
> that has **never** succeeded sorts to the very top with a blank date.

<DataTable data={ops_freshness} rows=9>
  <Column id=entity title="Entity"/>
  <Column id=last_ok_doc_type title="Last OK Dataset"/>
  <Column id=last_ok_year title="Year"/>
  <Column id=last_ok_month title="Month" fmt=num0/>
  <Column id=last_ok_rows title="Rows" fmt=num0/>
  <Column id=last_ok_at title="Last OK"/>
  <Column id=days_since_ok title="Days Since OK" fmt=num1/>
  <Column id=last_attempt_at title="Last Attempt"/>
  <Column id=last_attempt_status title="Last Status"/>
  <Column id=n_ok_30d title="OK (30d)" fmt=num0/>
  <Column id=n_error_30d title="Errors (30d)" fmt=num0/>
</DataTable>

---

## Status Breakdown per Dataset

> Every `(entity, doc_type)` seen in the last 30 days, worst-first by error
> count, with the most recent error text. An entity that produced **no runs at
> all** still appears — as a row with blank counts, which is the loudest signal
> on the page.
>
> Entity and doc-type labels here are the ones the pipeline writes to the log,
> not the old Flask dispatch keys: the log says `inf_diario` where that matrix
> called the same dataset `diario`.

<DataTable data={ops_status_by_dataset} rows=20 search=true>
  <Column id=entity title="Entity"/>
  <Column id=doc_type title="Doc Type"/>
  <Column id=n_runs title="Runs" fmt=num0/>
  <Column id=n_ok title="OK" fmt=num0/>
  <Column id=n_error title="Errors" fmt=num0/>
  <Column id=n_skipped title="Skipped" fmt=num0/>
  <Column id=ok_num1 title="OK (%)" fmt=num1/>
  <Column id=total_rows title="Rows (30d)" fmt=num0/>
  <Column id=last_run title="Last Run"/>
  <Column id=last_error_msg title="Last Error"/>
</DataTable>

---

## Table Freshness — What Actually Landed

> Read from the ingest tables themselves, not from the log. Each table is dated on
> its own natural key column, named in `Date Column` so grains are never silently
> mixed — `cvm_fip_periodic` is **yearly** and is shown at 31-Dec of its newest
> reporting year purely so the column is comparable.
>
> Expect a structural lag: CVM publishes monthly datasets 1–2 months in arrears,
> so a `Days Stale` of 30–90 on a monthly table is normal. An **empty** table
> sorts to the top with a blank date.

<DataTable data={ops_table_freshness} rows=10>
  <Column id=table_name title="Table"/>
  <Column id=date_column title="Date Column"/>
  <Column id=n_rows title="Rows" fmt=num0/>
  <Column id=latest title="Newest Row"/>
  <Column id=days_stale title="Days Stale" fmt=num0/>
</DataTable>

---

## Analytical Coverage per Month

> The downstream half: distinct funds present per month in `fact_fund_monthly`,
> by family. The log can say `ok` while the analytical layer still has a hole, and
> a month whose fund count collapses is a data problem the log alone would not
> show.
>
> Structural gaps that are **not** failures: FIP reports yearly (only its December
> month is populated), FIAGRO's monthly file only begins 2025-05, and the newest
> month or two are thin because of CVM's publication lag. Every page that depends
> on these families states the same caveat where it bites — see
> [Industry Structure](/industry) and [Performance](/performance).

<LineChart
data={ops_coverage}
x=period
y={['fi_funds','fidc_funds','fii_funds','fiagro_funds','fip_funds']}
yAxisTitle="Distinct Funds Reporting"
title="Funds Reporting per Month by Family"
/>

---

## Most Recent Runs

> The 20 newest rows of `cvm_ingest_log`, newest first. `Duration` is blank while
> a run is still `running` — the tell for a job that died without writing its
> terminal status. Blank rows at the bottom mean the log holds fewer than 20 runs.

<DataTable data={ops_recent_runs} rows=20>
  <Column id=slot title="#" fmt=num0/>
  <Column id=started_at title="Started"/>
  <Column id=entity title="Entity"/>
  <Column id=doc_type title="Doc Type"/>
  <Column id=period_year title="Year"/>
  <Column id=period_month title="Month" fmt=num0/>
  <Column id=status title="Status"/>
  <Column id=rows_upserted title="Rows" fmt=num0/>
  <Column id=duration_s title="Duration (s)" fmt=num1/>
  <Column id=error_msg title="Error"/>
</DataTable>

> Triage runbook for what to do with a red row: `docs/DATABASE_MAINTENANCE.md`.
