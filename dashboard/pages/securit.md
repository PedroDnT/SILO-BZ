---
title: Securitization
hide_title: true
sidebar_position: 10
---

<!--
  CRI / CRA / OTS certificates, NOT funds: modelled on dim_security / fact_security_monthly.
  cvm_securit_serie is a monthly RE-STATEMENT of the whole live book, so every
  "outstanding" figure de-duplicates to the latest data_referencia per series
  (instrument_type, codigo_identificacao, numero_serie) before summing, and counts only
  series whose latest filing is in the As Of month or the month before (#434). The
  trend is "reported value", not issuance: CVM publishes no clean issuance flow.
  Known gaps, none estimated: nivel_subordinacao is never written by any FIELD_MAP
  (always NULL); indice_subordinacao_minimo is unscaled (fraction or percentage is
  undocumented); cvm_securit_dfin is raw JSONB with only cnpj_securit parsed, so its
  section is coverage only; instrument_type is stored as the *_mensal label
  ('cri_mensal'), so queries match on prefix.
-->

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

> CRI (real-estate), CRA (agribusiness) and OTS (other) certificates, each a slice of a receivables pool (CVM, monthly, 1 to 2 months lag). These are **not funds**: no NAV, quotaholders or returns. The trend is **stock outstanding as re-stated each month**, not new issuance. Related: [FIDC Credit Monitor](/fidc), [Suspicious Deal Screens](/suspicious).

<BigValue data={securit_overview} value=n_series title="Live Series" fmt=num0/>
<BigValue data={securit_overview} value=n_securitizadoras title="Securitizadoras" fmt=num0/>
<BigValue data={securit_overview} value=outstanding_bn title="Outstanding (R$bn)" fmt=num0/>
<BigValue data={securit_overview} value=em_atraso_num1 title="Series Em Atraso (%)" fmt=num1/>
<BigValue data={securit_overview} value=as_of_period title="As Of"/>

> `Series Em Atraso` is a share of the **series count**, not of value. CVM files `Situacao` as Adimplente or Em atraso, never "Inadimplente"; CRI filings before 2022-07 carry no status, so those series are left out of the share, not counted as current. Every figure here counts series whose latest filing is in the `As Of` month or the month before; `As Of` is the newest month holding at least half the previous month's series.

---

## Reported Value by Instrument Family

> Monthly `valor_certificados` by family, from `security_issuance_trend()` (CVM, monthly, 1 to 2 months lag): **stock outstanding**, not new issuance. A step can be new deals, redemptions or a change in who filed. A month still receiving filings is left out, not drawn as a drop.

<AreaChart
data={securit_issuance_trend}
x=period
y={['cri_bn','cra_bn','ots_bn','outros_bn']}
type=stacked
yAxisTitle="R$bn"
  title="Outstanding Certificate Value by Family (R$bn)"
/>

<LineChart
  data={securit_issuance_trend}
  x=period
  y=em_atraso_num1
  yAxisTitle="% of Series"
  title="Share of Series Em Atraso"
/>

<DataTable data={securit_issuance_trend} rows=6>
  <Column id=period title="Period"/>
  <Column id=n_series title="Series Reported" fmt=num0/>
  <Column id=cri_bn title="CRI (R$bn)" fmt=num2/>
  <Column id=cra_bn title="CRA (R$bn)" fmt=num2/>
  <Column id=ots_bn title="OTS (R$bn)" fmt=num2/>
  <Column id=n_em_atraso title="Em Atraso" fmt=num0/>
  <Column id=em_atraso_num1 title="Series Em Atraso (%)" fmt=num1/>
  <Column id=n_outro_status title="Other Status" fmt=num0/>
</DataTable>

> `Other Status` counts series whose status is neither Adimplente nor Em atraso. It is 0 today; anything else means CVM filed a status this page does not classify.

---

## Maturity Wall

> Outstanding value by maturity year, from the latest filing of each live series (CVM, monthly). Built from `cvm_securit_serie`, not `security_maturity_ladder()`, which reads `dim_security` (no `valor_certificados`) and hardcodes `total_value` to NULL.

<BarChart
data={securit_maturity_wall}
x=maturity_year
y={['cri_bn','cra_bn','ots_bn']}
type=stacked
yAxisTitle="R$bn"
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

> The ladder runs 15 years forward only. Series past maturity or with no maturity date are counted separately below; the past-maturity series are listed on [Suspicious Deal Screens](/suspicious).

<BigValue data={securit_overview} value=n_past_maturity title="Past Maturity, Still Open" fmt=num0/>
<BigValue data={securit_overview} value=n_sem_vencimento title="No Maturity Date Filed" fmt=num0/>

---

## Payment Waterfall

> Each month's collections across the whole book, from `cvm_securit_fluxo` (CVM, monthly, 1 to 2 months lag). Payments go out in priority order: expenses, senior, mezzanine, junior. All legs are positive, as filed.

<AreaChart
data={securit_waterfall}
x=period
y={['pgt_despesas_mm','pgt_senior_mm','pgt_mezanino_mm','pgt_junior_mm']}
type=stacked
yAxisTitle="R$mm"
  title="Payments Out by Priority (R$mm)"
/>

<LineChart
data={securit_waterfall}
x=period
y={['recebimentos_mm','pgt_total_mm']}
yAxisTitle="R$mm"
  title="Receivables Collected vs Total Paid Out (R$mm)"
/>

<DataTable data={securit_waterfall} rows=6>
  <Column id=period title="Period"/>
  <Column id=recebimentos_mm title="Collected (R$mm)" fmt=num1/>
  <Column id=pgt_senior_mm title="Senior (R$mm)" fmt=num1/>
  <Column id=pgt_mezanino_mm title="Mezzanine (R$mm)" fmt=num1/>
  <Column id=pgt_junior_mm title="Junior (R$mm)" fmt=num1/>
  <Column id=pgt_despesas_mm title="Expenses (R$mm)" fmt=num1/>
  <Column id=cobertura_num1 title="Paid / Collected (%)" fmt=num1/>
  <Column id=n_securitizadoras title="Filers" fmt=num0/>
</DataTable>

> `Paid / Collected` above 100% means more paid out than collected that month, normal when an amortisation date draws on reserves, worth a look if it persists. A month with filings but no payment figures is blank, never zero.

---

## Credit Ratings

> `classificacao_risco_atual` is free text as filed (CVM, monthly), grouped verbatim: merging `brAAA` and `AAA(bra)` would be an assumption, not data.

<BarChart
  data={securit_ratings}
  x=rating
  y=value_bn
  swapXY=true
  yAxisTitle="R$bn"
  title="Outstanding Value by Rating (R$bn)"
/>

<DataTable data={securit_ratings} rows=12>
  <Column id=rating title="Rating (as filed)"/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=value_bn title="Outstanding (R$bn)" fmt=num2/>
  <Column id=n_em_atraso title="Em Atraso" fmt=num0/>
  <Column id=em_atraso_num1 title="Series Em Atraso (%)" fmt=num1/>
</DataTable>

---

## Subordination Structure

> Tranche classes as filed in `classe` (CVM, monthly). **`Índice Subord. Mínimo` is shown unscaled**: CVM does not document whether it is a fraction or a percentage. `Series w/ Nível` reads **0** because `nivel_subordinacao` exists in `schema.sql` but no `FIELD_MAP` entry populates it; it is counted so the gap stays visible.

<DataTable data={securit_subordination} rows=12>
  <Column id=classe title="Tranche Class (as filed)"/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=value_bn title="Outstanding (R$bn)" fmt=num2/>
  <Column id=idx_subord_min_median title="Índice Subord. Mínimo (median, unscaled)" fmt=num2/>
  <Column id=idx_subord_min_avg title="Índice Subord. Mínimo (mean, unscaled)" fmt=num2/>
  <Column id=n_with_idx title="Series w/ Index" fmt=num0/>
  <Column id=n_with_nivel title="Series w/ Nível" fmt=num0/>
  <Column id=em_atraso_num1 title="Series Em Atraso (%)" fmt=num1/>
</DataTable>

---

## Distressed Series

> Series whose latest filing carries a distressed `situacao` (Inadimplente, Em atraso or Cancelado), from `distressed_securities()` (CVM, monthly), largest first. An empty table means none at the latest period, not that the check did not run. Collected and Paid are filed per certificate, not per series, so series of one certificate repeat the same figures: do not add them across rows.

<DataTable data={securit_distressed} rows=15 search=true>
  <Column id=instrument title="Type"/>
  <Column id=codigo_identificacao title="Series Code"/>
  <Column id=numero_serie title="Série"/>
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

> **Coverage only, by design.** `cvm_securit_dfin` parses one column, `cnpj_securit`; every statement line is unparsed in `raw` (CVM, yearly). Charting revenue or equity would mean inventing it, so this counts filings.

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

> Blank years are not yet fetched; `dfin_cri` starts at 2018 and `dfin_cra` at 2019 upstream (`src/fetchers/cvm_config.py`). Fetch status: [Pipeline Ops](/ops).
