---
title: ETF Market
---

<!--
  ETFs are evaluated SEPARATELY from ordinary funds. They are carved out of the
  fund analytics (dim_fund / fact_fund_monthly exclude ETF CNPJs — see
  src/store/analytical/01_dim_fund.sql, 04_fact_fund_monthly.sql) and analysed on
  their own axis here.

  DATA COVERAGE: this page is built on cvm_etf_registry (187 ETFs, curated B3
  ticker→CNPJ seed enriched from cad_fi), which carries identity (provider,
  segment, underlying index, status) for ~all ETFs. ETF price/NAV/return time
  series (the etf_daily view + etf_performance_* functions in 16_etf_analysis.sql)
  are currently EMPTY because the registry's fund-level CNPJ does not match the
  share-class CNPJs in 2026 cvm_fi_diario (CVM-175 class split). Performance needs
  an ETF price feed — see the note at the bottom. Nothing here is fabricated;
  quantitative ETF metrics that aren't in the data are shown as gaps, not guesses.
-->

```sql etf_counts
select
  count(*)                              as total_etfs,
  count(*) filter (where is_active)     as active_etfs,
  count(distinct provider)              as providers,
  count(distinct underlying_index)      as indices_tracked
from cvm_etf_registry
```

```sql etf_by_provider
select
  coalesce(provider, '(unknown)')   as provider,
  count(*)                          as n_etfs,
  count(*) filter (where is_active) as active
from cvm_etf_registry
group by provider
order by n_etfs desc
```

```sql etf_by_segment
select
  coalesce(segment, '(unknown)') as segment,
  count(*)                       as n_etfs
from cvm_etf_registry
group by segment
order by n_etfs desc
```

```sql etf_top_indices
select
  coalesce(underlying_index, '(unknown)') as underlying_index,
  count(*)                                as n_etfs
from cvm_etf_registry
group by underlying_index
order by n_etfs desc
limit 15
```

```sql etf_list
select
  ticker,
  fund_name,
  provider,
  segment,
  underlying_index,
  case when is_active then 'Active' else 'Cancelled' end as status
from cvm_etf_registry
order by provider, ticker
```

# ETF Market

> Brazilian listed ETFs (Fundos de Índice), evaluated **separately** from the fund
> industry. Universe and structure from `cvm_etf_registry`.

<BigValue data={etf_counts} value=total_etfs label="Total ETFs"/>
<BigValue data={etf_counts} value=active_etfs label="Active"/>
<BigValue data={etf_counts} value=providers label="Providers"/>
<BigValue data={etf_counts} value=indices_tracked label="Indices Tracked"/>

---

## ETFs by Provider

<BarChart
  data={etf_by_provider}
  x=provider
  y=n_etfs
  swapXY=true
  title="ETF Count by Provider"
  yAxisTitle="ETFs"
/>

<DataTable data={etf_by_provider} rows=12>
  <Column id=provider title="Provider"/>
  <Column id=n_etfs title="ETFs" fmt=num0/>
  <Column id=active title="Active" fmt=num0/>
</DataTable>

---

## ETFs by Segment

<BarChart
  data={etf_by_segment}
  x=segment
  y=n_etfs
  swapXY=true
  title="ETF Count by Segment"
  yAxisTitle="ETFs"
/>

---

## Most-Tracked Underlying Indices

<DataTable data={etf_top_indices} rows=15>
  <Column id=underlying_index title="Underlying Index"/>
  <Column id=n_etfs title="ETFs" fmt=num0/>
</DataTable>

---

## ETF Universe

<DataTable data={etf_list} rows=20 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=fund_name title="Fund"/>
  <Column id=provider title="Provider"/>
  <Column id=segment title="Segment"/>
  <Column id=underlying_index title="Index"/>
  <Column id=status title="Status"/>
</DataTable>

---

## ⚠️ Performance & AUM — pending an ETF price feed

ETF **price, NAV, return, AUM and flow** series are **not yet available** in this
database, so they are intentionally **not shown** here rather than estimated:

- `etf_daily` joins the registry's fund-level CNPJ to `cvm_fi_diario`, but under
  CVM-175 the daily file keys on **share-class CNPJs**, so the join is currently
  empty.
- `cvm_etf_registry` carries AUM (`vl_patrim_liq`) for only 8/187 ETFs and no fees.
- The ANBIMA class series (`anbima_etf_class_monthly`, RF/RV AUM·flows·returns)
  has not been ingested yet.

The ETF performance functions are already defined in
`src/store/analytical/16_etf_analysis.sql`
(`etf_performance_ranking`, `etf_performance_series`, `etf_class_performance`) and
will populate this page automatically once an ETF price source lands — either by
fixing the registry↔class-CNPJ linkage, running the ANBIMA ETF ingest, or wiring an
external feed (e.g. etfsbrasil.com / FMP).
