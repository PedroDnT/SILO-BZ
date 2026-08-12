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
select * from supabase.etf_counts
```

```sql etf_by_provider
select * from supabase.etf_by_provider
```

```sql etf_by_segment
select * from supabase.etf_by_segment
```

```sql etf_top_indices
select * from supabase.etf_top_indices
```

```sql etf_list
select * from supabase.etf_list
```

```sql etf_market_coverage
select * from supabase.etf_market_coverage
```

```sql etf_market
select * from supabase.etf_market
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

## NAV, Price & Quotaholders

> Per-ETF market snapshot scraped from etfsbrasil.com.br (`etf_market_latest`, most
> recent snapshot per ticker). This feed exists because CVM open data no longer
> exposes ETF NAV/quotaholders post-CVM-175 — `etf_daily` (registry ⋈ `cvm_fi_diario`)
> stays empty because the registry's fund-level CNPJ no longer matches the daily
> file's class-level CNPJ. Values shown straight from source; missing fields are
> gaps, never estimates. The table is empty until the first scrape lands (the
> `run_daily` scrape runs only when `APIFY_TOKEN` is configured).

<BigValue data={etf_market_coverage} value=etfs_with_snapshot label="ETFs w/ Snapshot"/>
<BigValue data={etf_market_coverage} value=with_nav label="With NAV"/>
<BigValue data={etf_market_coverage} value=with_cotistas label="With Quotaholders"/>
<BigValue data={etf_market_coverage} value=latest_snapshot label="Latest Snapshot"/>

<DataTable data={etf_market} rows=20 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=fund_name title="Fund"/>
  <Column id=provider title="Provider"/>
  <Column id=segment title="Segment"/>
  <Column id=price title="Price (R$)" fmt='#,##0.00'/>
  <Column id=nav title="NAV / AUM (R$)" fmt=num0/>
  <Column id=cotistas title="Quotaholders" fmt=num0/>
  <Column id=taxa_adm_pct title="Adm Fee %" fmt='#,##0.00'/>
  <Column id=ret_12m_pct title="12m Return %" fmt='#,##0.00'/>
  <Column id=snapshot_date title="As Of"/>
</DataTable>

> **Returns / volatility / Sharpe / drawdown** (`ret_*`, `vol_12m_pct`,
> `sharpe_12m`, `max_drawdown_pct`) stay blank until the scraper's `next_data`
> (`__NEXT_DATA__`) JSON is mapped to those columns — they are chart-rendered on the
> source page, not in the scraped text, so they are left NULL rather than guessed.
> The horizontal/vertical ETF performance functions
> (`etf_performance_series`, `etf_performance_ranking`, `etf_class_performance`) in
> `src/store/analytical/16_etf_analysis.sql` remain available for any pre-CVM-175 ETF
> that still resolves through `etf_daily`.
