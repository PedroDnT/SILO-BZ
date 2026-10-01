---
title: ETF Market
hide_title: true
sidebar_position: 11
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

```sql etf_fixed_income
select * from supabase.etf_fixed_income
```

```sql etf_fixed_income_family
select
  family,
  count(ticker)        as n_etfs,
  sum(nav_mm) / 1000   as nav_bn,
  max(nav_date)        as nav_date
from supabase.etf_fixed_income
where ticker is not null
group by family
order by nav_bn desc
```

```sql etf_fixed_income_prints_family
select
  p.trade_date,
  coalesce(f.family, 'Unmapped')  as family,
  sum(p.notional_mm)              as notional_mm
from supabase.etf_fixed_income_prints p
left join supabase.etf_fixed_income f on f.ticker = p.ticker
where p.ticker is not null
group by 1, 2
order by 1, 2
```

```sql etf_fixed_income_prints_latest
with latest as (
  select max(trade_date) as d from supabase.etf_fixed_income_prints
),
per_ticker as (
  select
    ticker,
    count(*)            as sessions,
    avg(notional_mm)    as avg_notional_mm
  from supabase.etf_fixed_income_prints
  where ticker is not null
  group by ticker
)
select
  p.ticker,
  f.family,
  p.last_price,
  p.notional_mm,
  p.trade_count,
  t.avg_notional_mm,
  t.sessions,
  p.trade_date
from supabase.etf_fixed_income_prints p
join latest l on p.trade_date = l.d
left join supabase.etf_fixed_income f on f.ticker = p.ticker
left join per_ticker t on t.ticker = p.ticker
order by p.notional_mm desc
```

```sql etf_anbima_total
select * from supabase.etf_anbima_total
```

```sql etf_anbima_by_type_long
select period, 'Fixed income' as class, pl_fixed_income_bn as pl_bn, flow_fixed_income_bn as flow_bn
from supabase.etf_anbima_by_type
union all
select period, 'Equity' as class, pl_equity_bn, flow_equity_bn
from supabase.etf_anbima_by_type
order by class, period
```

# ETF Market

> Brazilian listed ETFs (Fundos de Índice), evaluated **separately** from the fund
> industry — they are carved out of `dim_fund` and `fact_fund_monthly` upstream,
> so no ETF appears anywhere else on this site.
>
> The honest headline is a gap: **identity is complete, quantities are not.**
> The registry knows who issues each ETF, what it tracks and whether it is active,
> so the structure sections are solid. But CVM's post-CVM-175 share-class split
> broke the CNPJ join `etf_daily` depended on, so NAV, price and return history are
> largely absent; what remains is a scraped snapshot that only runs when an API
> token is configured. Nothing has been back-filled to close that gap.

<BigValue data={etf_counts} value=total_etfs title="Total ETFs" fmt=num0/>
<BigValue data={etf_counts} value=active_etfs title="Active" fmt=num0/>
<BigValue data={etf_counts} value=providers title="Brands" fmt=num0/>
<BigValue data={etf_counts} value=indices_tracked title="Indices Tracked" fmt=num0/>

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

## Brazilian Fixed Income ETFs

> The 46 ETFs the registry labels `fixed_income_br`, grouped by the index they
> track. The family is mapped from the registry's index name (the rule is in
> `etf_fixed_income.sql`); the index name sits next to it so the mapping can be
> checked. Net assets are CVM's published figure with its own date. The close is
> the previous session's B3 price as carried by the etfsbrasil snapshot, dated by
> the snapshot.
>
> **Exchange prints:** below. B3 lists these ETFs in segment FORWARD, which its
> COTAHIST tape does not carry, so their prints come from B3's consolidated trade
> file instead. Quotaholders are in the snapshot table further down. Returns,
> volatility and Sharpe are empty in the snapshot for every ETF.

<BarChart
  data={etf_fixed_income_family}
  x=family
  y=nav_bn
  swapXY=true
  yAxisTitle="Net Assets (R$bn)"
  title="Fixed Income ETF Net Assets by Index Family (R$bn, CVM)"
/>

<DataTable data={etf_fixed_income_family}>
  <Column id=family title="Index Family"/>
  <Column id=n_etfs title="ETFs" fmt=num0/>
  <Column id=nav_bn title="Net Assets (R$bn)" fmt=num1/>
  <Column id=nav_date title="Latest NAV Date"/>
</DataTable>

<DataTable data={etf_fixed_income} rows=15 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=family title="Index Family"/>
  <Column id=index_name title="Index Tracked"/>
  <Column id=brand title="Brand"/>
  <Column id=nav_mm title="Net Assets, CVM (R$mm)" fmt=num1/>
  <Column id=nav_date title="NAV Date"/>
  <Column id=cotistas title="Quotaholders" fmt=num0/>
  <Column id=price title="Close, B3 (R$)" fmt='#,##0.00'/>
  <Column id=snapshot_date title="Snapshot Date"/>
</DataTable>

### Exchange Prints (B3 Consolidated Trade File)

> Daily traded value and last price of the 46 fixed income ETFs, from B3's
> TradeInformationConsolidatedFile (`b3_trade_consolidated`). They trade in B3's
> segment FORWARD, which COTAHIST omits, so the equity ETF volume chart further
> down does not include them, and the two volume measures are not comparable.
> Traded value is in R$ million as B3 reports it. Daily, final files only. The
> history starts at the first session loaded; B3 keeps the file back to
> 2025-06-10.

<BarChart
  data={etf_fixed_income_prints_family}
  x=trade_date
  y=notional_mm
  series=family
  type=stacked
  yAxisTitle="R$mm"
  title="Fixed Income ETF Traded Value per Session, by Index Family (R$mm, B3)"
/>

<DataTable data={etf_fixed_income_prints_latest} rows=15 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=family title="Index Family"/>
  <Column id=last_price title="Last Price (R$)" fmt='#,##0.00'/>
  <Column id=notional_mm title="Traded, Latest Session (R$mm)" fmt=num1/>
  <Column id=trade_count title="Trades" fmt=num0/>
  <Column id=avg_notional_mm title="Avg Traded per Session (R$mm)" fmt=num1/>
  <Column id=sessions title="Sessions Held" fmt=num0/>
  <Column id=trade_date title="Session"/>
</DataTable>

---

## ETF Industry Net Assets and Flows (ANBIMA)

> ANBIMA's monthly bulletin, as held in `anbima_class_monthly`. Total ETF net
> assets are one point per year-end from 2006 to 2024, then monthly from 2025;
> nothing is drawn between year-ends. The fixed income and equity split, and
> monthly net flows, start 2025-01 in this table. Monthly, published with about
> a month's lag.

<LineChart
  data={etf_anbima_total}
  x=reference_date
  y=pl_bn
  markers=true
  yAxisTitle="R$bn"
  title="ETF Net Assets, All Classes (R$bn, ANBIMA)"
/>

<LineChart
  data={etf_anbima_by_type_long}
  x=period
  y=pl_bn
  series=class
  yAxisTitle="R$bn"
  title="ETF Net Assets: Fixed Income vs Equity (R$bn, ANBIMA)"
/>

<BarChart
  data={etf_anbima_by_type_long}
  x=period
  y=flow_bn
  series=class
  type=grouped
  yAxisTitle="R$bn"
  title="ETF Net Flows per Month: Fixed Income vs Equity (R$bn, ANBIMA)"
/>

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

> Monthly ETF activity from the COTAHIST tape: exchange volume, distinct tickers
> that printed, and the median close. **Unadjusted exchange price/volume** — it
> fills the time axis NAV-based ETF metrics cannot, since those stay sparse
> post-CVM-175.
>
> The median close is a cross-sectional "typical print", **not an index**: ETFs
> quote at very different price points and the mix shifts as ETFs list, so it says
> nothing about returns. ETF rows come from B3's own board codes (CODBDI 14),
> never from ticker shape.

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

> Per-ETF snapshot scraped from etfsbrasil.com.br. This feed exists because CVM open
> data no longer exposes ETF NAV/quotaholders post-CVM-175: `etf_daily` stays empty
> because the registry's fund-level CNPJ no longer matches the daily file's
> class-level CNPJ.
>
> Values are straight from source; missing fields are gaps, never estimates. Empty
> until the first scrape lands — it runs only when `APIFY_TOKEN` is configured
> ([Pipeline Ops](/ops) says whether it has).

<BigValue data={etf_market_coverage} value=etfs_with_snapshot title="ETFs w/ Snapshot" fmt=num0/>
<BigValue data={etf_market_coverage} value=with_nav title="With NAV" fmt=num0/>
<BigValue data={etf_market_coverage} value=with_cotistas title="With Quotaholders" fmt=num0/>
<BigValue data={etf_market_coverage} value=latest_snapshot title="Latest Snapshot"/>

<DataTable data={etf_market} rows=20 search=true>
  <Column id=ticker title="Ticker"/>
  <Column id=fund_name title="Fund"/>
  <Column id=manager title="Manager (CVM)"/>
  <Column id=administrator title="Administrator"/>
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
