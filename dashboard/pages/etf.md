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

  SECTION ORDER runs identity (who issues what, tracking which index) before the
  market snapshot, because identity is the part that is fully populated and the
  snapshot is the part that is gated on a secret. The lede states the gap up
  front so nobody reads the structure sections as a complete ETF dataset.

  The "Exchange Price and Volume" section (etf_market_series) is B3 COTAHIST
  tape data — exchange volume/close of instrument_subtype='etf' rows via
  vw_b3_instrument_typed — and sits between identity and the snapshot because
  it is fully populated (2019+) while NAV-side series are not. Unadjusted
  prices; the median close is cross-sectional, not an index.
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

```sql etf_market_series
select * from supabase.etf_market_series
```

# ETF Market

> Brazilian listed ETFs (Fundos de Índice), evaluated **separately** from the fund
> industry — they are carved out of `dim_fund` and `fact_fund_monthly` upstream,
> so no ETF appears anywhere else on this site.
>
> The honest headline is a gap. **Identity is complete; quantities are not.**
> `cvm_etf_registry` knows who issues each ETF, what it tracks and whether it is
> active, so the structure sections below are solid. But CVM's post-CVM-175
> share-class split broke the CNPJ join that `etf_daily` depended on, so NAV,
> price and return history are largely absent, and what remains comes from a
> scraped snapshot that only runs when an API token is configured. Nothing has
> been back-filled to close that gap. Fund performance on comparable measures is
> on [Performance](/performance).

<BigValue data={etf_counts} value=total_etfs label="Total ETFs" fmt=num0/>
<BigValue data={etf_counts} value=active_etfs label="Active" fmt=num0/>
<BigValue data={etf_counts} value=providers label="Brands" fmt=num0/>
<BigValue data={etf_counts} value=indices_tracked label="Indices Tracked" fmt=num0/>

---

## ETFs by Brand

> Count of listed ETFs per product brand (the curated seed label — "It Now",
> "Trend" — not the CVM manager and not the index publisher). This is a count of
> vehicles, **not** of assets: a brand with many small ETFs outranks one with a
> single large fund.

<BarChart
  data={etf_by_provider}
  x=provider
  y=n_etfs
  swapXY=true
  yAxisTitle="ETFs"
  title="ETF Count by Brand"
/>

<DataTable data={etf_by_provider} rows=12>
  <Column id=provider title="Brand"/>
  <Column id=n_etfs title="ETFs" fmt=num0/>
  <Column id=active title="Active" fmt=num0/>
</DataTable>

---

## ETFs by Segment

> The same count split by the registry's segment label — equity, fixed income,
> international and so on.

<BarChart
  data={etf_by_segment}
  x=segment
  y=n_etfs
  swapXY=true
  yAxisTitle="ETFs"
  title="ETF Count by Segment"
/>

---

## Most-Tracked Underlying Indices

> Where several ETFs track one index, they are close substitutes competing mainly
> on fee and liquidity — neither of which the registry carries.

<DataTable data={etf_top_indices} rows=15>
  <Column id=underlying_index title="Underlying Index"/>
  <Column id=n_etfs title="ETFs" fmt=num0/>
</DataTable>

---

## ETF Universe

> The full registry, searchable by ticker, fund name, manager or index. `Status`
> is CVM's own registry status, not a liquidity or delisting judgement.
>
> **Manager, brand and index are three different things.** `Manager (CVM)` is the
> gestor as published in CVM's cad_fi registry — the firm that runs the fund.
> `Brand` is the curated product family label. `Index Tracked` is the index, and
> the index's publisher (Bloomberg, S&P, Teva, B3…) is usually named inside it —
> that firm indexes the fund, it does not manage it.

<DataTable data={etf_list} rows=20 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=fund_name title="Fund"/>
  <Column id=manager title="Manager (CVM)"/>
  <Column id=brand title="Brand"/>
  <Column id=index_name title="Index Tracked"/>
  <Column id=segment title="Segment"/>
  <Column id=status title="Status"/>
</DataTable>

---

## Exchange Price and Volume — B3 Tape

> Monthly ETF activity from the B3 COTAHIST tape: total exchange volume and the
> number of distinct ETF tickers that printed, plus the median close across all
> ETF prints. This is **exchange price/volume, unadjusted, straight from
> COTAHIST** — it fills the time axis that NAV-based ETF metrics cannot, since
> those remain sparse post-CVM-175 (see below). The median close is a
> cross-sectional "typical print", not an index: ETFs quote at very different
> price points, and the mix shifts as ETFs list, so it says nothing about
> returns. ETF rows are identified from B3's own board codes
> (`vw_b3_instrument_typed`, CODBDI 14), never from ticker shape; the full
> exchange tape is on [B3 Markets](/markets).

<LineChart
  data={etf_market_series}
  x=period
  y=volume_bn
  yAxisTitle="Volume (R$bn)"
  title="ETF Exchange Volume per Month (R$bn)"
/>

<LineChart
  data={etf_market_series}
  x=period
  y=n_etf_tickers
  yAxisTitle="Tickers"
  title="Distinct ETF Tickers Traded per Month"
/>

<LineChart
  data={etf_market_series}
  x=period
  y=median_close
  yAxisTitle="R$"
  title="Median ETF Close Across Prints (R$, unadjusted)"
/>

---

## NAV, Price and Quotaholders

> Per-ETF market snapshot scraped from etfsbrasil.com.br (`etf_market_latest`, most
> recent snapshot per ticker). This feed exists because CVM open data no longer
> exposes ETF NAV/quotaholders post-CVM-175 — `etf_daily` (registry ⋈ `cvm_fi_diario`)
> stays empty because the registry's fund-level CNPJ no longer matches the daily
> file's class-level CNPJ. Values shown straight from source; missing fields are
> gaps, never estimates. The table is empty until the first scrape lands (the
> `run_daily` scrape runs only when `APIFY_TOKEN` is configured — see
> [Pipeline Ops](/ops) for whether it has run).

<BigValue data={etf_market_coverage} value=etfs_with_snapshot label="ETFs w/ Snapshot" fmt=num0/>
<BigValue data={etf_market_coverage} value=with_nav label="With NAV" fmt=num0/>
<BigValue data={etf_market_coverage} value=with_cotistas label="With Quotaholders" fmt=num0/>
<BigValue data={etf_market_coverage} value=latest_snapshot label="Latest Snapshot"/>

<DataTable data={etf_market} rows=20 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=fund_name title="Fund"/>
  <Column id=manager title="Manager (CVM)"/>
  <Column id=index_name title="Index Tracked"/>
  <Column id=price title="Close, B3 (R$)" fmt='#,##0.00'/>
  <Column id=price_date title="Close Date"/>
  <Column id=nav title="Net Assets, CVM (R$)" fmt=num0/>
  <Column id=nav_date title="NAV Date"/>
  <Column id=cotistas title="Quotaholders" fmt=num0/>
  <Column id=taxa_adm_num2 title="Adm Fee (%)" fmt=num2/>
  <Column id=ret_12m_num2 title="12m Return (%)" fmt=num2/>
</DataTable>

> **Returns, volatility, Sharpe and drawdown** (`ret_*`, `vol_12m_pct`,
> `sharpe_12m`, `max_drawdown_pct`) stay blank until the scraper's `next_data`
> (`__NEXT_DATA__`) JSON is mapped to those columns — they are chart-rendered on the
> source page, not in the scraped text, so they are left NULL rather than guessed.
> The horizontal/vertical ETF performance functions
> (`etf_performance_series`, `etf_performance_ranking`, `etf_class_performance`) in
> `src/store/analytical/16_etf_analysis.sql` remain available for any pre-CVM-175 ETF
> that still resolves through `etf_daily`.
