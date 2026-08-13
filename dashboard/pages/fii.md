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

  SECTION ORDER runs size → yield → who pays the most → what the filings actually
  contain → whether the payouts are covered → the buildings. Filing coverage sits
  immediately before the payout section because it is what makes a blank payout
  column readable.

  CHART-TYPE NOTE: FII vs FIAGRO net assets is a time series of two levels, so it
  is a LineChart. It was previously a grouped BarChart, which is the site's
  convention for per-period FLOWS, not for stocks.
-->

```sql fii_vs_fiagro
select * from supabase.fii_vs_fiagro
```

```sql yield_distribution
select * from supabase.yield_distribution
```

```sql top_fii_yield
select * from supabase.top_fii_yield
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

> Real-estate funds are bought for the monthly distribution, so the question that
> matters is whether the distribution is earned. This page reads the sector's
> dividend yield, then measures declared payouts against the funds' own books, then
> looks at the buildings underneath.
>
> Two limits. A payout above what the book yields is **not** evidence of anything
> on its own — it is consistent with realised gains, with a return of capital, and
> with amortisation; the numbers are shown side by side and no verdict is asserted.
> And the property detail is **partial**: CVM leaves vacancy and delinquency blank
> for a large minority of buildings, so those columns are reported against their own
> denominator rather than averaged. FIAGRO, the
> agribusiness sibling charted below, is covered in more depth on
> [Industry Structure](/industry).

---

## FII vs FIAGRO Net Assets

> Two families on the same axis over 24 months. FIAGRO's monthly file only begins
> **2025-05**, so its line starts there — the earlier absence is the dataset not
> existing, not a fund count of zero.

<LineChart
  data={fii_vs_fiagro}
  x=period
  y=aum_bn
  series=entity_type
  yAxisTitle="Net Assets (R$bn)"
  title="FII vs FIAGRO Net Assets"
/>

---

## Yield Distribution Across FIIs — p10 to p90

> The spread, not the average. A widening gap between p10 and p90 means the sector
> is separating into funds that distribute and funds that do not, which a median
> alone conceals.

<LineChart
data={yield_distribution}
x=period
y={['p10','p25','median','p75','p90']}
yAxisTitle="Dividend Yield (%)"
title="FII Monthly Dividend Yield Distribution"
/>

---

## Top 25 FIIs by Dividend Yield

> Funds with more than R$50mm in net assets, ranked on CVM's reported
> `pct_dividend_yield_mes`. A very high yield on this measure is a reason to read
> the payout-coverage table further down, not a conclusion on its own.

<DataTable data={top_fii_yield} rows=25>
  <Column id=fund_name title="Fund"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=investors title="Quotaholders" fmt=num0/>
  <Column id=dy_pct title="Dividend Yield (%)" fmt=num2/>
  <Column id=return_pct title="Return (%)" fmt=num2/>
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
  <Column id=with_vpc title="With Book Value / Quota" fmt=num0/>
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
  yAxisTitle="Income to Distribute (R$mm)"
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
  <Column id=payout_mm title="Income to Distribute (R$mm)" fmt=num1/>
  <Column id=pl_bn title="Net Assets (R$bn)" fmt=num2/>
  <Column id=assets_bn title="Total Assets (R$bn)" fmt=num2/>
  <Column id=payout_pct_of_pl title="Payout / Net Assets (%)" fmt=num2/>
  <Column id=n_funds title="Funds in Month" fmt=num0/>
  <Column id=n_funds_payout title="…Reporting Payout" fmt=num0/>
  <Column id=n_funds_assets title="…Reporting Assets" fmt=num0/>
  <Column id=n_funds_cotas title="…Reporting Quotas" fmt=num0/>
</DataTable>

> Fund by fund below, latest month. `Payout Yield on Book` is the monthly payout
> per quota over the book value per quota (`vl_patrimonial_cotas`).
> `Reported DY` is CVM's own `pct_dividend_yield_mes`, the measure the top-25 table
> above uses. The two are shown side by side rather than reconciled, because they
> come from different filings — a large divergence between them is itself worth
> checking against the fund's report.

<DataTable data={fii_payout_coverage} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=payout_mm title="Income to Distribute (R$mm)" fmt=num1/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=vl_ativo_mm title="Total Assets (R$mm)" fmt=num1/>
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

<BigValue data={fii_property_coverage} value=property_rows label="Buildings Registered" fmt=num0/>
<BigValue data={fii_property_coverage} value=funds_with_register label="Funds with a Register" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_with_invested_share label="…with an Invested Share" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_with_vacancy label="…with Vacancy Reported" fmt=num0/>
<BigValue data={fii_property_coverage} value=rows_single_asset_over_50pct label="Single Asset > 50% Invested" fmt=num0/>

> **Coverage first.** These rows come from `cvm_fii_imovel`, the per-building
> register CVM ships as its own member of the `INF_TRIMESTRAL` zip. Until
> recently the fetcher was pulling the wrong member of that zip — the _alienação_
> file, which lists buildings being **sold** — so this table previously described
> disposals rather than holdings. CVM leaves vacancy and delinquency blank for a
> large minority of buildings, which is why those tiles are shown as their own
> denominator rather than folded into an average.
>
> **Single-asset concentration:** a fund where one property is more than half of
> everything it has invested has no diversification left — one tenant, one lease,
> one roof. Those rows are flagged in the Concentration column. The share is of
> the fund's **invested assets**, not of its net assets, and CVM publishes the
> `pr_*` fields without a documented scale, so they are shown in **source units**
> and read as a ranking rather than as a percentage. A fund concentrated in its
> investor base rather than its assets is the captive-vehicle screen on
> [Suspicious Deal Screens](/suspicious).

<DataTable data={fii_property_explorer} rows=20 search=true>
  <Column id=fund_name title="Fund"/>
  <Column id=nome_imovel title="Property"/>
  <Column id=classe title="Class"/>
  <Column id=endereco title="Address"/>
  <Column id=area title="Area (m²)" fmt=num0/>
  <Column id=numero_unidades title="Units" fmt=num0/>
  <Column id=pct_invested title="Share of Invested (source units)" fmt=num2/>
  <Column id=vacancia title="Vacancy (source units)" fmt=num2/>
  <Column id=inadimplencia title="Delinquency (source units)" fmt=num2/>
  <Column id=concentration_flag title="Concentration"/>
  <Column id=data_referencia title="Ref Date"/>
</DataTable>
