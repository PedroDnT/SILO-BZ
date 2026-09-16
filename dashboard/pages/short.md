---
title: Short Monitor
hide_title: true
sidebar_position: 4
---

<!--
  Aluguel & posição vendida on B3, from the public securities-lending book
  (b3_lending_open_position + b3_lending_rate via fact_short_interest_daily).

  THE THREE THINGS A READER MUST KNOW, all stated in the lede rather than
  buried here:

    1. HISTORY IS SHORT BY CONSTRUCTION. B3 retains ~21 business days of this
       data and publishes no archive (verified 2026-09-16: 2026-08-17 returns
       rows, 2026-08-14 returns "Nenhum resultado", and a 2024→2026 range comes
       back HTTP 200 with 18 sessions). The series therefore starts the day
       SILO began capturing and can never be backfilled. Every chart on this
       page names its own coverage instead of implying more.

    2. "% DO FREE FLOAT" IS TWO METRICS. B3 publishes a real free float only
       for index constituents (b3_index_portfolio.theoretical_qty, ~150
       tickers). For the rest the denominator is shares outstanding, which is
       LARGER and so yields a SMALLER percentage. The ranking table is
       free-float-only for that reason, and the basis split below it shows how
       much of the book each basis covers. Never merge the two into one rank.

    3. THE DOUBLE-COUNT TRAP. B3 publishes per-market rows AND its own
       Mercado='Total' sum for every (session, ticker, spec). fact_short_
       interest_daily reads the Total rows only; a naive SUM over the landing
       table is exactly 2x the real short balance.

  ETF/BDR HANDLING: the ranked tables filter to categoria in (SHARES, UNIT).
  Index ETFs dominate an unfiltered days-to-cover screen (PIBB11 at ~110 days,
  BOVA11 at ~32) because they sit on loan against thin secondary volume. That
  is true and is not what "crowded short" means. They stay in the totals and in
  the basis split, so nothing is hidden — only the RANKINGS are equities.

  ZERO-ROW SAFETY: the headline is aggregate-single-row with coalesce; the
  ranked tables and the sector bar return zero rows on a fresh database, which
  Evidence renders as empty rather than failing the build.
-->

```sql headline
select * from supabase.short_headline
```

```sql top_float
select * from supabase.short_top_float
```

```sql top_sir
select * from supabase.short_top_sir
```

```sql top_rate
select * from supabase.short_top_rate
```

```sql by_sector
select * from supabase.short_by_sector
```

```sql history
select * from supabase.short_history
```

```sql basis_split
select * from supabase.short_basis_split
```

# Short Monitor — Aluguel & Posição Vendida

> Who is short what, at what cost, on B3's public securities-lending book. Every
> figure comes from B3's own daily lending files: the open position per ticker,
> and the annualized rates lenders received and borrowers paid.
>
> **This series cannot be backfilled.** B3 keeps roughly 21 business days of
> lending data and publishes no archive, so the history below starts when SILO
> began capturing it and grows one session per day. A gap here is permanent, not
> late — which is the opposite of every CVM page on this dashboard.
>
> **Read `% do free float` with its basis.** B3 publishes a true free float only
> for index constituents; for everything else the honest denominator is shares
> outstanding, a larger number that yields a smaller percentage. The ranking
> below is free-float-only so the rows are comparable. The split is charted at
> the foot of the page.

{#if headline[0].trade_date}

<BigValue data={headline} value=trade_date title="Latest Session"/>
<BigValue data={headline} value=short_brl_equities title="Short Book — Equities (R$)" fmt=num0/>
<BigValue data={headline} value=tickers_short title="Equity Tickers on Loan" fmt=num0/>
<BigValue data={headline} value=sessions_held title="Sessions Captured" fmt=num0/>

<Alert status=info>
Coverage runs from <Value data={headline} column=first_session/> to
<Value data={headline} column=trade_date/> —
<Value data={headline} column=sessions_held/> sessions. B3 retains about 21
business days and keeps no archive, so anything earlier is unrecoverable at any
price.
</Alert>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

---

## Maiores Posições Short — % do Free Float

> Short interest as a share of the free float B3 publishes for index
> constituents. These are the positions that are large relative to the shares
> actually available to buy back.
>
> Equities and units only. Index ETFs carry large loan balances against their
> own quota count for creation/redemption reasons that have nothing to do with a
> directional view.

{#if headline[0].trade_date}

<DataTable data={top_float} rows=20>
  <Column id=rank title="#" align=center/>
  <Column id=ticker/>
  <Column id=asset_name title="Empresa"/>
  <Column id=sector title="Setor"/>
  <Column id=pct_float title="Short (% Float)" fmt='0.0"%"' contentType=colorscale scaleColor=red/>
  <Column id=short_brl title="Posição (R$)" fmt=num0/>
  <Column id=days_to_cover title="SIR (d)" fmt=num1/>
  <Column id=taxa_tomador_aa title="Taxa (a.a.)" fmt='0.0"%"'/>
</DataTable>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

## Maior SIR — Days to Cover

> Short Interest Ratio: how many sessions of average volume it would take to buy
> the position back, against the trailing 21-session ADTV. A high ratio is a
> crowded exit, not merely a large position.
>
> Positions under R$5mn are excluded — a small short on an illiquid name
> produces an enormous and meaningless ratio. `Sessões` is how many sessions the
> ADTV average actually covers; fewer than 21 means a shorter, noisier window.

{#if headline[0].trade_date}

<DataTable data={top_sir} rows=20>
  <Column id=rank title="#" align=center/>
  <Column id=ticker/>
  <Column id=asset_name title="Empresa"/>
  <Column id=days_to_cover title="SIR (dias)" fmt=num1 contentType=colorscale scaleColor=red/>
  <Column id=short_brl title="Posição (R$)" fmt=num0/>
  <Column id=adtv_brl_21 title="ADTV 21d (R$)" fmt=num0/>
  <Column id=adtv_sessions title="Sessões" fmt=num0/>
</DataTable>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

## Maiores Taxas de Aluguel

> The annualized rate borrowers paid, quantity-weighted across B3's lending
> markets for the session. Expensive borrow is the market pricing scarcity —
> it usually moves before the position does.
>
> Markets with no registered quantity publish a nominal rate on no business and
> are excluded, which is what keeps a dormant BDR off the top of this table.

{#if headline[0].trade_date}

<DataTable data={top_rate} rows=20>
  <Column id=rank title="#" align=center/>
  <Column id=ticker/>
  <Column id=asset_name title="Empresa"/>
  <Column id=taxa_tomador_aa title="Taxa Tomador (a.a.)" fmt='0.0"%"' contentType=colorscale scaleColor=red/>
  <Column id=taxa_doador_aa title="Taxa Doador (a.a.)" fmt='0.0"%"'/>
  <Column id=short_brl title="Posição (R$)" fmt=num0/>
  <Column id=num_contratos title="Contratos" fmt=num0/>
</DataTable>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

---

## Posições Short por Setor

> The equity short book aggregated by B3's own top-level sector. Only SHARES and
> UNIT are counted: ETFs and BDRs carry no B3 sector, and including them would
> make an unclassified bucket the largest bar on a chart about single-name risk.

{#if headline[0].trade_date}

<BarChart
  data={by_sector}
  x=sector
  y=short_brl
  swapXY=true
  yAxisTitle="Posição Short (R$)"
  title="Short Book by B3 Sector — Equities Only (R$)"
/>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

## Evolução do Short Book

> Total short balance per session over the window SILO holds. A short line here
> means recent coverage, not a quiet market.

{#if headline[0].trade_date}

<LineChart
  data={history}
  x=trade_date
  y={['short_brl_equities','short_brl']}
  yAxisTitle="Posição Short (R$)"
  title="Short Balance per Session — Equities vs All Instruments (R$)"
/>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}

## Qual Denominador — Free Float ou Capital Social

> How much of the short book can be stated as a percentage of true free float at
> all. `index_free_float` rows are the ones the ranking table uses;
> `shares_outstanding` rows are real positions measured against a larger
> denominator, so their percentages are not comparable to the ranking above;
> `sem denominador` is a ticker B3 published neither figure for, whose `% float`
> is NULL rather than zero.

{#if headline[0].trade_date}

<DataTable data={basis_split}>
  <Column id=float_basis title="Base"/>
  <Column id=tickers title="Tickers" fmt=num0/>
  <Column id=short_brl title="Posição (R$)" fmt=num0/>
</DataTable>

{:else}

<Alert status=warning>
**No lending sessions captured yet.** B3 keeps roughly 21 business days of the
securities-lending files and publishes no archive, so this page begins at SILO's
first daily capture and grows one session per day. Nothing is missing that can
be recovered — the first `run_daily` after deploy fills it.
</Alert>

{/if}
