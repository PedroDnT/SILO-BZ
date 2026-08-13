---
title: FI Industry
---

<!--
  The FI (fundos de investimento) industry — by far the largest entity in the
  warehouse. Sources, in order of trustworthiness:

    cvm_fi_diario   — daily NAV/flows, the spine of everything here. Multi-GB and
                      RANGE-partitioned by year, so every query below is bounded
                      by a date window AND aggregated (see fi_daily_flow.sql).
    fact_fund_monthly / dim_fund — the monthly matviews the rest of the dashboard
                      uses; ETFs are carved out of them (they live on /etf).
    cvm_fi_cda      — portfolio composition. USABLE FOR MIX, NOT FOR LEVELS: the
                      table keys on (cnpj, period, tp_aplic, tp_ativo) and upserts
                      DO UPDATE, so a fund's many security rows inside one bucket
                      collapse to the last one written instead of summing.
    cvm_fi_perfil   — investor profile. The nr_cotst_* / pr_* columns exist in
                      schema.sql but are NOT in the perfil FIELD_MAP
                      (src/parsers/field_maps/fi_perfil.py), so they normally sit
                      in the residual `raw` JSONB. Every perfil query here reads
                      the typed column first and falls back to the raw CVM key;
                      when neither resolves the value stays NULL and the coverage
                      tile says so. Nothing is imputed, rescaled or back-filled.

  Every source query is driven by a generate_series spine or a no-GROUP-BY
  aggregate so it can never return zero rows (a 0-row source writes a 0-byte
  parquet and kills the whole Evidence build).

  SECTION ORDER runs size → flow → investors (headcount, then mix, then the
  single-holder screen that the mix data makes possible) → portfolio → the fund
  directory. The concentration screen sits inside the investor block because it
  reads the same PERFIL file and inherits the same coverage caveat.

  CHART-TYPE NOTE: daily subscriptions/redemptions are drawn as lines, not bars,
  even though monthly flows elsewhere on the site are bars — 120 daily bars per
  series is unreadable. The rule is monthly flow → BarChart, high-frequency flow
  → LineChart.
-->

```sql fi_headline
select * from supabase.fi_headline
```

```sql fi_aum_trend
select * from supabase.fi_aum_trend
```

```sql fi_daily_flow
select * from supabase.fi_daily_flow
```

```sql fi_quotaholders
select * from supabase.fi_quotaholders
```

```sql fi_perfil_coverage
select * from supabase.fi_perfil_coverage
```

```sql fi_investor_mix
select * from supabase.fi_investor_mix
```

```sql fi_investor_split
select * from supabase.fi_investor_split
```

```sql fi_concentration
select * from supabase.fi_concentration
```

```sql fi_allocation
select * from supabase.fi_allocation
```

```sql fi_top_aplic
select * from supabase.fi_top_aplic
```

```sql fi_top_funds
select * from supabase.fi_top_funds
```

# FI Industry

> Open-ended investment funds are the overwhelming majority of the Brazilian fund
> industry by net assets, and the only family that reports **daily** — so this is
> the one place on the site where flows can be watched as they happen rather than
> one to two months in arrears.
>
> Two things this page cannot tell you. The portfolio book comes from CDA, whose
> natural key collapses a fund's security-level rows to one per bucket, so the
> allocation section is a **directional mix and not a market-value census**. And
> the investor split comes from PERFIL, most of whose holder-count columns are not
> lifted by the field map — the coverage tiles state exactly how much resolves
> before any chart is drawn from it. ETFs are excluded here and analysed on
> [the ETF page](/etf).

<BigValue data={fi_headline} value=aum_bn label="Industry Net Assets (R$bn)" fmt=num0/>
<BigValue data={fi_headline} value=n_funds label="Funds Reporting" fmt=num0/>
<BigValue data={fi_headline} value=investors label="Quotaholder Positions" fmt=num0/>
<BigValue data={fi_headline} value=net_flow_bn label="Net Flow, Latest Month (R$bn)" fmt=num0/>
<BigValue data={fi_headline} value=latest_period label="Latest Month"/>

---

## Industry Net Assets — 36 Months

> `industry_aum_trend(['fi'], …)`. Months the industry has not published yet come
> back empty rather than being carried forward. The same series alongside the
> other four families is on [Industry Structure](/industry).

<LineChart
  data={fi_aum_trend}
  x=period
  y=aum_bn
  yAxisTitle="Net Assets (R$bn)"
  title="FI Industry Net Assets"
/>

<BarChart
  data={fi_aum_trend}
  x=period
  y=net_flow_bn
  yAxisTitle="Net Flow (R$bn)"
  title="FI Monthly Net Flow (Subscriptions − Redemptions)"
/>

---

## Daily Flow — Last 120 Days

> `sum(captc_dia) − sum(resg_dia)` per business day over a bounded window of
> `cvm_fi_diario`, aggregated in Postgres — the raw table is multi-GB and is never
> selected row-by-row. Holidays and non-reporting days appear as gaps, not zeros.

<LineChart
data={fi_daily_flow}
x=dt_comptc
y={['inflow_bn','outflow_bn']}
yAxisTitle="R$bn per Day"
title="Daily Subscriptions vs Redemptions"
/>

<AreaChart
  data={fi_daily_flow}
  x=dt_comptc
  y=cum_net_flow_bn
  yAxisTitle="Cumulative Net Flow (R$bn)"
  title="Cumulative Net Flow Over the Window"
/>

<DataTable data={fi_daily_flow} rows=10>
  <Column id=dt_comptc title="Date"/>
  <Column id=n_funds title="Funds Reporting" fmt=num0/>
  <Column id=aum_tn title="Net Assets (R$tn)" fmt=num2/>
  <Column id=inflow_bn title="Subscriptions (R$bn)" fmt=num2/>
  <Column id=outflow_bn title="Redemptions (R$bn)" fmt=num2/>
  <Column id=net_flow_bn title="Net Flow (R$bn)" fmt=num2/>
</DataTable>

---

## Quotaholder Base

> Headcount from `quotaholder_trend('fi', …)`, i.e. `nr_cotst` on the daily file.
> This is independent of the PERFIL class split below and is the reliable
> "how many investors" series. It counts **positions, not people**: one investor
> holding three funds appears three times.

<LineChart
  data={fi_quotaholders}
  x=period
  y=investors_mm
  yAxisTitle="Quotaholder Positions (millions)"
  title="FI Quotaholder Positions"
/>

---

## Investor Mix — Retail vs Institutional

<BigValue data={fi_perfil_coverage} value=funds_reporting label="Funds in Latest PERFIL File" fmt=num0/>
<BigValue data={fi_perfil_coverage} value=funds_with_investor_split label="…with an Investor Split" fmt=num0/>
<BigValue data={fi_perfil_coverage} value=funds_with_holder_share label="…with a Largest-Holder Share" fmt=num0/>
<BigValue data={fi_perfil_coverage} value=latest_period label="PERFIL Period"/>

> **Coverage first.** The `nr_cotst_*` holder buckets are declared on
> `cvm_fi_perfil` but have not historically been lifted by the perfil field map,
> so they sit in the residual `raw` JSONB; every query in this section reads the
> typed column and falls back to the raw CVM key, and leaves the value NULL when
> neither resolves. If the two tiles above read zero, the charts below are empty
> **because the data is not lifted yet** — nothing has been estimated to fill the
> space.
>
> **"Retail" here is a modelled subset, not the retail base.** The split sums
> seven buckets — individuals in private banking plus retail corporates on the
> retail side — and **excludes CVM's mass-retail individual bucket**
> (`NR_COTST_PF_VAREJO`) entirely, so the retail count and the retail share are
> both understatements by construction. Use the quotaholder series above for
> "how many investors"; use this one only for the direction of the mix.

<AreaChart
  data={fi_investor_mix}
  x=period
  y=holders_k
  series=investor_class
  yAxisTitle="Quotaholders (thousands)"
  title="FI Investor Base by Class"
/>

<LineChart
  data={fi_investor_split}
  x=period
  y=retail_pct
  yAxisTitle="Retail Share of Modelled Base (%)"
  title="Retail Share of the FI Investor Base"
/>

<DataTable data={fi_investor_split} rows=8>
  <Column id=period title="Month"/>
  <Column id=retail_k title="Retail (thousands)" fmt=num0/>
  <Column id=institutional_k title="Institutional (thousands)" fmt=num0/>
  <Column id=retail_pct title="Retail Share (%)" fmt=num1/>
  <Column id=n_funds title="Funds in File" fmt=num0/>
  <Column id=n_funds_with_split title="Funds with Split" fmt=num0/>
</DataTable>

---

## Single-Holder Concentration Screen

> A fund whose largest quotaholder owns most of the net assets behaves like a
> managed account: one redemption decision can unwind it. `pr_patrim_liq_maior_cotst`
> is published by CVM as a `PR_` field and the parser deliberately does **not**
> rescale it (fraction vs percent varies by file), so the column below is in
> **source units** — read it as a ranking, and check the raw file before quoting a
> number as a percentage. Funds are ordered by that share, then by size.
>
> This is the FI counterpart of the captive-vehicle screen for FIIs on
> [Suspicious Deal Screens](/suspicious); both look for a vehicle with one investor
> behind it.

<DataTable data={fi_concentration} rows=15 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=largest_holder_share title="Largest-Holder Share (source units)" fmt=num2/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=investors title="Quotaholders" fmt=num0/>
  <Column id=credit_priv_share title="Private-Credit Share (source units)" fmt=num2/>
  <Column id=period title="PERFIL Period"/>
</DataTable>

---

## Portfolio Allocation

> From `cvm_fi_cda`. **Directional mix, not a market-value census:** the table's
> natural key is `(cnpj, period, tp_aplic, tp_ativo)` and the ingest upserts
> `ON CONFLICT DO UPDATE`, so the many security-level rows a fund reports inside
> one bucket collapse to the last one written rather than summing. Use the shape
> of the stack and the ranking; treat the R$ levels as a lower bound. The top
> eight asset types are shown individually, everything else is bucketed.

<AreaChart
  data={fi_allocation}
  x=period
  y=value_bn
  series=asset_type
  yAxisTitle="Reported Position (R$bn)"
  title="FI Book by Asset Type (tp_ativo)"
/>

> Application types below are at the latest CDA period, on the same lower-bound
> caveat. `Share of Observed CDA Total` is a share of what was observed, not of
> the industry's actual book.

<DataTable data={fi_top_aplic} rows=20>
  <Column id=tp_aplic title="Application Type"/>
  <Column id=value_bn title="Reported Position (R$bn)" fmt=num2/>
  <Column id=share_pct title="Share of Observed CDA Total (%)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=period title="Period"/>
</DataTable>

---

## Largest FI Funds

> `fund_ranking('fi', 'aum', …)` joined to `dim_fund` for the label. The ranking
> function returns no name of its own; where `cvm_fund_registry` has not populated
> one, the CNPJ is shown rather than a guess. Per-fund history and the full
> searchable universe are on [Fund Explorer](/fund); how these funds ranked on
> return rather than size is on [Performance](/performance).

<DataTable data={fi_top_funds} rows=25 search=true>
  <Column id=rank_pos title="#" fmt=num0/>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=aum_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=investors title="Quotaholders" fmt=num0/>
  <Column id=net_flow_mm title="Net Flow (R$mm)" fmt=num1/>
  <Column id=quota title="Quota Value (R$)" fmt='#,##0.00'/>
  <Column id=period title="Month"/>
</DataTable>
