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

> Brazilian open-ended investment funds — the largest slice of the fund universe.
> Net assets and daily flows come straight from `cvm_fi_diario`; the investor
> split and the portfolio book come from the monthly PERFIL and CDA files, each
> with its own coverage caveat stated where it matters. ETFs are excluded here and
> analysed on [the ETF page](/etf).

<BigValue data={fi_headline} value=aum_bn label="Industry AUM (R$ bn)" fmt=num0/>
<BigValue data={fi_headline} value=n_funds label="Funds Reporting" fmt=num0/>
<BigValue data={fi_headline} value=investors label="Quotaholder Positions" fmt=num0/>
<BigValue data={fi_headline} value=net_flow_bn label="Net Flow, Latest Month (R$ bn)" fmt=num1/>
<BigValue data={fi_headline} value=latest_period label="Latest Month"/>

---

## Industry Net Assets — 36 Months

> `industry_aum_trend(['fi'], …)`. Months the industry has not published yet come
> back empty rather than being carried forward.

<LineChart
  data={fi_aum_trend}
  x=period
  y=aum_bn
  yAxisTitle="Net Assets (R$ bn)"
  title="FI Industry Net Assets"
/>

<BarChart
  data={fi_aum_trend}
  x=period
  y=net_flow_bn
  yAxisTitle="Net Flow (R$ bn)"
  title="FI Monthly Net Flow (subscriptions − redemptions)"
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
yAxisTitle="R$ bn per day"
title="Daily Subscriptions vs Redemptions"
/>

<AreaChart
  data={fi_daily_flow}
  x=dt_comptc
  y=cum_net_flow_bn
  yAxisTitle="Cumulative Net Flow (R$ bn)"
  title="Cumulative Net Flow Over the Window"
/>

<DataTable data={fi_daily_flow} rows=10>
  <Column id=dt_comptc title="Date"/>
  <Column id=n_funds title="Funds Reporting" fmt=num0/>
  <Column id=aum_tn title="Net Assets (R$ tn)" fmt=num2/>
  <Column id=inflow_bn title="Subscriptions (R$ bn)" fmt=num2/>
  <Column id=outflow_bn title="Redemptions (R$ bn)" fmt=num2/>
  <Column id=net_flow_bn title="Net (R$ bn)" fmt=num2/>
</DataTable>

---

## Quotaholder Base

> Headcount from `quotaholder_trend('fi', …)`, i.e. `nr_cotst` on the daily file.
> This is independent of the PERFIL class split below and is the reliable
> "how many investors" series.

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

> **Coverage first.** The seven `nr_cotst_*` buckets are declared on
> `cvm_fi_perfil` but are not mapped by the perfil field map, so they normally
> live in the residual `raw` JSONB; these queries read the typed column and fall
> back to the raw CVM key. If the two tiles above read zero, the charts in this
> section are empty **because the data is not lifted yet** — nothing has been
> estimated to fill the space. Note also that CVM's mass-retail individual bucket
> is not among the columns the schema lifts, so "retail" here is the modelled
> retail subset (individuals in private banking + retail corporates) and
> understates the true retail base.

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

<DataTable data={fi_concentration} rows=15 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=largest_holder_share title="Largest-Holder Share (source units)" fmt=num2/>
  <Column id=pl_mm title="Net Assets (R$ mm)" fmt=num0/>
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
  yAxisTitle="Reported Position (R$ bn)"
  title="FI Book by Asset Type (tp_ativo)"
/>

### Top Application Types — Latest CDA Period

<DataTable data={fi_top_aplic} rows=20>
  <Column id=tp_aplic title="Application Type"/>
  <Column id=value_bn title="Reported Position (R$ bn)" fmt=num1/>
  <Column id=share_pct title="Share of Observed CDA Total (%)" fmt=num1/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=period title="Period"/>
</DataTable>

---

## Largest FI Funds

> `fund_ranking('fi', 'aum', …)` joined to `dim_fund` for the label. The ranking
> function returns no name of its own; where `cvm_fund_registry` has not populated
> one, the CNPJ is shown rather than a guess. Per-fund history lives on
> [the fund explorer](/fund).

<DataTable data={fi_top_funds} rows=25 search=true>
  <Column id=rank_pos title="#" fmt=num0/>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=aum_bn title="Net Assets (R$ bn)" fmt=num2/>
  <Column id=investors title="Quotaholders" fmt=num0/>
  <Column id=net_flow_mm title="Net Flow (R$ mm)" fmt=num1/>
  <Column id=quota title="Quota Value (R$)" fmt='#,##0.00'/>
  <Column id=period title="Month"/>
</DataTable>
