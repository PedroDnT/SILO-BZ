---
title: FII Market
---

<!--
  Real-estate funds. The AUM / dividend-yield sections read cvm_fii_mensal's
  `complemento` subtype (the only one the dashboard used originally); the payout
  and property sections added below read the subtypes that were ingested but never
  surfaced:

    ativo_passivo → vl_ativo (Total_Investido), rendimentos_distribuir
    geral         → cotas_emitidas
    complemento   → vl_patrim_liq, vl_patrimonial_cotas, pct_dividend_yield_mes

  PROPERTY DETAIL IS PARTIAL BY CONSTRUCTION. cvm_fii_periodic declares
  nome_imovel / endereco / area / numero_unidades / percentual_imovel_pl in
  schema.sql, but the periodic FIELD_MAP maps only cnpj + data_referencia, and the
  fetcher pulls the main member of the INF_TRIMESTRAL zip while CVM ships the
  per-building detail in a separate member. The explorer therefore reads the typed
  column first and falls back to a case-insensitive scan of the residual `raw`
  JSONB, and leaves the cell blank when neither has it. A coverage tile states how
  many rows resolve, so an empty table reads as an ingestion gap rather than as an
  absence of buildings.

  Every source query is driven by a generate_series spine, a one-row VALUES spine,
  or a no-GROUP-BY aggregate, so none can return zero rows (a 0-row source writes
  a 0-byte parquet and kills the Evidence build).
-->

```sql fii_vs_fiagro
select * from supabase.fii_vs_fiagro
```

```sql top_fii_yield
select * from supabase.top_fii_yield
```

```sql yield_distribution
select * from supabase.yield_distribution
```

```sql fii_mensal_coverage
select * from supabase.fii_mensal_coverage
```

```sql fii_payout_trend
select * from supabase.fii_payout_trend
```

```sql fii_payout_coverage
select * from supabase.fii_payout_coverage
```

```sql fii_property_coverage
select * from supabase.fii_property_coverage
```

```sql fii_property_explorer
select * from supabase.fii_property_explorer
```

# FII Market

> Real estate investment funds: net assets, dividend yield, **payout coverage**
> against the funds' own books, and the **individual properties** behind them.

---

## FII vs FIAGRO AUM

<BarChart
  data={fii_vs_fiagro}
  x=period
  y=aum_bn
  series=entity_type
  type=grouped
  yAxisTitle="AUM (R$ bn)"
  title="FII vs FIAGRO Total AUM"
/>

---

## Yield Distribution Across FIIs — p10 to p90

<LineChart
data={yield_distribution}
x=period
y={['p10','p25','median','p75','p90']}
yAxisTitle="Dividend Yield (%)"
title="FII Monthly Dividend Yield Distribution"
/>

---

## Top 25 FIIs by Dividend Yield (AUM > R$50mm)

<DataTable data={top_fii_yield} rows=25>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num0/>
  <Column id=investors title="Investors" fmt=num0/>
  <Column id=dy_pct title="DY %" fmt=num2/>
  <Column id=return_pct title="Return %" fmt=num2/>
</DataTable>

---

## Which FII Filings Are Populated

> `cvm_fii_mensal` carries three ingested subtypes. Only `complemento` fed the
> charts above; the payout section below reads `ativo_passivo` and `geral`. This
> table is the ground truth for what is present, so a blank payout column can be
> read as "not filed / not mapped" rather than "no distribution".

<DataTable data={fii_mensal_coverage} rows=5>
  <Column id=doc_subtype title="Subtype"/>
  <Column id=n_rows title="Rows" fmt=num0/>
  <Column id=n_funds title="Funds" fmt=num0/>
  <Column id=first_period title="First Month"/>
  <Column id=latest_period title="Latest Month"/>
  <Column id=with_pl title="With Net Assets" fmt=num0/>
  <Column id=with_ativo title="With Total Assets" fmt=num0/>
  <Column id=with_cotas title="With Quotas Issued" fmt=num0/>
  <Column id=with_vpc title="With Book Value/Quota" fmt=num0/>
  <Column id=with_rendimentos title="With Income to Distribute" fmt=num0/>
</DataTable>

---

## Payout Coverage

> `rendimentos_distribuir` (income the fund has declared for distribution, from
> the `ativo_passivo` filing) measured against the fund's own book: net assets,
> quotas outstanding, and book value per quota. A fund distributing far more than
> its book yields is paying out of capital or realised gains — the numbers are
> shown, the verdict is not asserted. The `n_funds_*` columns track how many funds
> reported each field, so a fall in the sector total can be told apart from a fall
> in coverage.

<LineChart
  data={fii_payout_trend}
  x=period
  y=payout_mm
  yAxisTitle="Income to Distribute (R$ mm)"
  title="FII Sector Income Declared for Distribution"
/>

<LineChart
  data={fii_payout_trend}
  x=period
  y=payout_pct_of_pl
  yAxisTitle="Payout / Net Assets (%)"
  title="Sector Payout as a Share of Net Assets"
/>

<DataTable data={fii_payout_trend} rows=12>
  <Column id=period title="Month"/>
  <Column id=payout_mm title="Income to Distribute (R$ mm)" fmt=num1/>
  <Column id=pl_bn title="Net Assets (R$ bn)" fmt=num1/>
  <Column id=assets_bn title="Total Assets (R$ bn)" fmt=num1/>
  <Column id=payout_pct_of_pl title="Payout / Net Assets (%)" fmt=num2/>
  <Column id=n_funds title="Funds in Month" fmt=num0/>
  <Column id=n_funds_payout title="…Reporting Payout" fmt=num0/>
  <Column id=n_funds_assets title="…Reporting Assets" fmt=num0/>
  <Column id=n_funds_cotas title="…Reporting Quotas" fmt=num0/>
</DataTable>

### Top 50 Payers — Latest Month

> `payout_yield_pct` is the monthly payout per quota over the book value per
> quota (`vl_patrimonial_cotas`). `reported_dy_pct` is CVM's own
> `pct_dividend_yield_mes` on the same convention the rest of this page uses; the
> two are shown side by side rather than reconciled, because they come from
> different filings.

<DataTable data={fii_payout_coverage} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=payout_mm title="Income to Distribute (R$ mm)" fmt=num2/>
  <Column id=pl_mm title="Net Assets (R$ mm)" fmt=num0/>
  <Column id=vl_ativo_mm title="Total Assets (R$ mm)" fmt=num0/>
  <Column id=payout_pct_of_pl title="Payout / Net Assets (%)" fmt=num2/>
  <Column id=cotas_emitidas title="Quotas Issued" fmt=num0/>
  <Column id=vpc title="Book Value / Quota (R$)" fmt='#,##0.00'/>
  <Column id=payout_per_cota title="Payout / Quota (R$)" fmt='#,##0.00'/>
  <Column id=payout_yield_pct title="Payout Yield on Book (%)" fmt=num2/>
  <Column id=reported_dy_pct title="Reported DY (%)" fmt=num2/>
  <Column id=period title="Month"/>
</DataTable>

---

## Property Explorer

<BigValue data={fii_property_coverage} value=periodic_rows label="Periodic Filing Rows" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_with_property_name label="…with a Property Name" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_with_pl_share label="…with a % of PL" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_single_asset_over_50pct label="Single Asset > 50% of PL" fmt=num0/>
<BigValue data={fii_property_coverage} value=latest_period_year label="Latest Filing Year"/>

> **Coverage first.** The property columns are declared on `cvm_fii_periodic` but
> the periodic field map lifts only `cnpj` and `data_referencia`, and the fetcher
> pulls the main member of the `INF_TRIMESTRAL` zip while CVM ships the
> per-building detail in a separate member. This table reads the typed column,
> falls back to the residual `raw` JSONB, and leaves the cell blank when neither
> resolves. If the tiles above read zero, the rows below are fund identities with
> no building attached — an ingestion gap, not an absence of real estate.
>
> **Single-asset concentration:** a fund where one property is more than 50% of
> net assets has no diversification left — one tenant, one lease, one roof. Those
> rows are flagged in the last column; `pct_of_pl` is shown in source units and is
> not rescaled.

<DataTable data={fii_property_explorer} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=nome_imovel title="Property"/>
  <Column id=endereco title="Address"/>
  <Column id=area title="Area (m²)" fmt=num0/>
  <Column id=numero_unidades title="Units" fmt=num0/>
  <Column id=pct_of_pl title="% of Net Assets (source units)" fmt=num2/>
  <Column id=single_asset_flag title="Concentration"/>
  <Column id=doc_type title="Filing"/>
  <Column id=period_year title="Year"/>
</DataTable>
