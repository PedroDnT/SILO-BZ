---
title: Securitization
---

<!--
  CRI / CRA / OTS securitised debt certificates. These are NOT investment funds:
  they are certificates issued by securitizadoras against a pool of receivables,
  so they sit outside dim_fund / fact_fund_monthly entirely and are modelled on
  their own axis (dim_security, fact_security_monthly).

  WHAT THE NUMBERS ARE. cvm_securit_serie is a monthly RE-STATEMENT of the whole
  live book — every series is filed again each month for as long as it exists.
  Every "outstanding" figure on this page therefore de-duplicates to the latest
  data_referencia per series (instrument_type, cnpj_securit,
  codigo_identificacao, numero_serie) before summing. Summing the table raw would
  multiply each series by the number of months it has been reported.

  For the same reason, the trend section is labelled "reported value", not
  "issuance": security_issuance_trend() sums valor_certificados per month, which
  is the stock outstanding in that month's filings, not new-issuance flow. CVM
  does not publish a clean issuance flow series here, so none is shown.

  KNOWN GAPS, none of them filled with estimates:
    * nivel_subordinacao — column exists in cvm_securit_serie (schema.sql ALTER)
      but no FIELD_MAP entry writes it, so it is always NULL. The subordination
      section reports its coverage count rather than pretending it is populated.
    * indice_subordinacao_minimo IS populated, but CVM does not document whether
      it is a fraction or a percentage, so it is shown unscaled and unlabelled
      as "%".
    * cvm_securit_dfin is raw JSONB with only cnpj_securit parsed
      (securit_dfin.py: "All other fields fall through to residual raw"), so its
      section is filing COVERAGE only — there is no balance sheet to chart yet.
    * instrument_type in cvm_securit_serie / _fluxo is stored as the *_mensal
      label ('cri_mensal', …), not the 'cri_classe' spelling that the
      dim_security comment and yield_universe()'s default still use. Queries
      here match on prefix so either spelling classifies correctly.
-->

```sql securit_overview
select * from supabase.securit_overview
```

```sql securit_issuance_trend
select * from supabase.securit_issuance_trend
```

```sql securit_maturity_wall
select * from supabase.securit_maturity_wall
```

```sql securit_waterfall
select * from supabase.securit_waterfall
```

```sql securit_ratings
select * from supabase.securit_ratings
```

```sql securit_subordination
select * from supabase.securit_subordination
```

```sql securit_distressed
select * from supabase.securit_distressed
```

```sql securit_dfin_coverage
select * from supabase.securit_dfin_coverage
```

# Securitization

> Brazilian securitised debt — CRI (real-estate), CRA (agribusiness) and OTS
> (other) certificates. Each series is a slice of a receivables pool, so the
> questions that matter are structural: when does it come due, who gets paid
> first, and is the pool still paying.

<BigValue data={securit_overview} value=n_series label="Live Series"/>
<BigValue data={securit_overview} value=n_securitizadoras label="Securitizadoras"/>
<BigValue data={securit_overview} value=outstanding_bn label="Outstanding (R$bn)" fmt=num1/>
<BigValue data={securit_overview} value=inadimplente_pct label="Inadimplente %" fmt=num1/>
<BigValue data={securit_overview} value=last_reference label="Latest Reference"/>

---

## Reported Value by Instrument Family

> Monthly `valor_certificados` by family, from `security_issuance_trend()`. This
> is the **stock outstanding** as re-stated in each month's filings — not new
> issuance. A step in the line is a change in what is on the book, which can be
> new deals, redemptions, or a change in who filed that month.

<AreaChart
data={securit_issuance_trend}
x=period
y={['cri_bn','cra_bn','ots_bn','outros_bn']}
type=stacked
yAxisTitle="R$ bn"
title="Outstanding Certificate Value by Family (R$bn)"
/>

<LineChart
  data={securit_issuance_trend}
  x=period
  y=inadimplente_pct
  yAxisTitle="% of series"
  title="Share of Series Marked Inadimplente"
/>

<DataTable data={securit_issuance_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=n_series title="Series Reported" fmt=num0/>
  <Column id=cri_bn title="CRI (R$bn)" fmt=num1/>
  <Column id=cra_bn title="CRA (R$bn)" fmt=num1/>
  <Column id=ots_bn title="OTS (R$bn)" fmt=num1/>
  <Column id=n_inadimplente title="Inadimplente" fmt=num0/>
  <Column id=inadimplente_pct title="Inadimplente %" fmt=num1/>
</DataTable>

---

## Maturity Wall

> Outstanding certificate value by maturity year, from the latest snapshot of
> each series. Built from `cvm_securit_serie` rather than
> `security_maturity_ladder()` — that function reads `dim_security`, which does
> not carry `valor_certificados`, and hardcodes `total_value` to NULL.

<BarChart
data={securit_maturity_wall}
x=maturity_year
y={['cri_bn','cra_bn','ots_bn']}
type=stacked
yAxisTitle="R$ bn"
title="Outstanding Value by Maturity Year (R$bn)"
/>

<DataTable data={securit_maturity_wall} rows=10>
  <Column id=maturity_year title="Maturity Year"/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=value_bn title="Total (R$bn)" fmt=num2/>
  <Column id=cri_bn title="CRI (R$bn)" fmt=num2/>
  <Column id=cra_bn title="CRA (R$bn)" fmt=num2/>
  <Column id=ots_bn title="OTS (R$bn)" fmt=num2/>
</DataTable>

> The ladder runs 15 years forward only. Series already past maturity, and series
> filed with no maturity date at all, are counted separately below rather than
> folded into a bucket they do not belong in.

<BigValue data={securit_overview} value=n_past_maturity label="Past Maturity, Still Open"/>
<BigValue data={securit_overview} value=n_sem_vencimento label="No Maturity Date Filed"/>

---

## Payment Waterfall

> Where each month's collections went, aggregated across the whole book, from
> `cvm_securit_fluxo`. Receivables come in at the top; payments go out in
> priority order — expenses first, then senior, mezzanine, and junior last. All
> legs are plotted as positive amounts, as filed.

<AreaChart
data={securit_waterfall}
x=period
y={['pgt_despesas_mm','pgt_senior_mm','pgt_mezanino_mm','pgt_junior_mm']}
type=stacked
yAxisTitle="R$ mm"
title="Payments Out by Priority (R$mm)"
/>

<LineChart
data={securit_waterfall}
x=period
y={['recebimentos_mm','pgt_total_mm']}
yAxisTitle="R$ mm"
title="Receivables Collected vs Total Paid Out (R$mm)"
/>

<DataTable data={securit_waterfall} rows=6>
  <Column id=period title="Period"/>
  <Column id=recebimentos_mm title="Collected (R$mm)" fmt=num1/>
  <Column id=pgt_senior_mm title="Senior (R$mm)" fmt=num1/>
  <Column id=pgt_mezanino_mm title="Mezzanine (R$mm)" fmt=num1/>
  <Column id=pgt_junior_mm title="Junior (R$mm)" fmt=num1/>
  <Column id=pgt_despesas_mm title="Expenses (R$mm)" fmt=num1/>
  <Column id=cobertura_pct title="Paid / Collected %" fmt=num1/>
  <Column id=n_securitizadoras title="Filers" fmt=num0/>
</DataTable>

> `Paid / Collected %` above 100 means the structure paid out more than it
> collected that month — normal for an amortisation date drawing on reserves,
> and worth a second look when it persists. A month with filings but no payment
> figures at all reports blank, never zero.

---

## Credit Ratings

> `classificacao_risco_atual` is free text as filed — different agencies,
> different scales, and several spellings of "no rating" coexist. Values are
> grouped verbatim; collapsing e.g. `brAAA` and `AAA(bra)` into one label would
> be an assumption, not data.

<BarChart
  data={securit_ratings}
  x=rating
  y=value_bn
  swapXY=true
  yAxisTitle="R$ bn"
  title="Outstanding Value by Rating (R$bn)"
/>

<DataTable data={securit_ratings} rows=12>
  <Column id=rating title="Rating (as filed)"/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=value_bn title="Outstanding (R$bn)" fmt=num2/>
  <Column id=n_inadimplente title="Inadimplente" fmt=num0/>
  <Column id=inadimplente_pct title="Inadimplente %" fmt=num1/>
</DataTable>

---

## Subordination Structure

> Tranche classes as filed in `classe`, with the minimum subordination index
> reported alongside. **`Índice Subord. Mínimo` is shown unscaled**: CVM does not
> document whether the field is a fraction or a percentage, and both conventions
> appear across filings, so it is not converted into a "%" here.

<DataTable data={securit_subordination} rows=12>
  <Column id=classe title="Tranche Class (as filed)"/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=value_bn title="Outstanding (R$bn)" fmt=num2/>
  <Column id=idx_subord_min_median title="Índice Subord. Mínimo (median, unscaled)" fmt=num2/>
  <Column id=idx_subord_min_avg title="Índice Subord. Mínimo (mean, unscaled)" fmt=num2/>
  <Column id=n_with_idx title="Series w/ Index" fmt=num0/>
  <Column id=n_with_nivel title="Series w/ Nível" fmt=num0/>
  <Column id=inadimplente_pct title="Inadimplente %" fmt=num1/>
</DataTable>

> `Series w/ Nível` will read **0** until the parser is extended.
> `cvm_securit_serie.nivel_subordinacao` exists in `schema.sql` but no
> `FIELD_MAP` entry populates it, so the column is structurally always NULL
> today. It is counted here rather than omitted so the gap stays visible — the
> tranche ordering above comes from `classe`, which is populated.

---

## Distressed Series

> Series whose latest filing carries a distressed `situacao` — Inadimplente, Em
> atraso, or Cancelado — from `distressed_securities()`. Largest by outstanding
> value first. An empty table here means no series in the book carried a
> distressed status at the latest period, not that the check did not run.

<DataTable data={securit_distressed} rows=15 search=true>
  <Column id=instrument title="Type"/>
  <Column id=codigo_identificacao title="Series Code"/>
  <Column id=numero_serie title="Série" fmt=num0/>
  <Column id=cnpj_securit title="Securitizadora CNPJ"/>
  <Column id=situacao_mes title="Status"/>
  <Column id=data_vencimento title="Maturity"/>
  <Column id=value_mm title="Outstanding (R$mm)" fmt=num1/>
  <Column id=recebimentos_mm title="Collected (R$mm)" fmt=num1/>
  <Column id=pgt_senior_mm title="Paid Senior (R$mm)" fmt=num1/>
  <Column id=pgt_junior_mm title="Paid Junior (R$mm)" fmt=num1/>
</DataTable>

---

## Financial Statement Coverage

> **Coverage only — there is no financial analysis in this section, by design.**
> `cvm_securit_dfin` is stored as `(instrument_type, period_year, cnpj_securit,
raw JSONB)`, and its field map parses exactly one column, `cnpj_securit`;
> every statement line is still unparsed inside `raw`. Charting revenue or
> equity from this table would mean inventing it, so this counts filings and
> stops there.

<BarChart
data={securit_dfin_coverage}
x=period_year
y={['n_cri','n_cra','n_outros']}
type=stacked
yAxisTitle="Filings"
title="DFIN Filings Ingested per Year"
/>

<DataTable data={securit_dfin_coverage} rows=9>
  <Column id=period_year title="Year"/>
  <Column id=n_cri title="dfin_cri Filings" fmt=num0/>
  <Column id=n_cra title="dfin_cra Filings" fmt=num0/>
  <Column id=n_outros title="Other Filings" fmt=num0/>
  <Column id=n_securitizadoras title="Distinct Securitizadoras" fmt=num0/>
</DataTable>

> Blank years are years not yet fetched. `dfin_cri` starts at 2018 and
> `dfin_cra` at 2019 upstream (`src/fetchers/cvm_config.py`), so a blank before
> those dates is expected rather than a gap.
