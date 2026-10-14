---
title: Filing Behaviour
hide_title: true
sidebar_position: 18
---

<!--
  The three screens are defined ONCE, as api.screen_late_filers(),
  api.screen_silent_filers() and api.screen_restatements() in
  src/store/analytical/25_api_filing_screens.sql. No public screen sits under
  them, so the sources call the api functions with their defaults written out
  and only format, order and cap the rows. The page and the API cannot disagree
  about who crossed a threshold.

  THRESHOLDS ARE ARGUMENTS, not findings, and the page states them:
    screen_late_filers(12, null, 5, 2, null)     12 months, 5 days late, 2 late months
    screen_silent_filers(3, 24, null)            3..24 complete months silent
    screen_restatements(12, null, 3, 20, null)   12 months, 3 re-filings, 20%

  The daily counts, the restatement list and the FIDC diff read the FNET
  register tables directly (fnet_document, fnet_document_filter,
  fnet_document_pair, fnet_document_diff). api.fund_restatements() is not
  called: at its default 30-day window it returns more than 1000 rows and
  refuses (22023), and a refusing source kills the build.

  Every list source has a zero-row guard (one all-NULL row), filtered here.
-->

```sql headline
select * from supabase.filings_headline
```

```sql daily
select * from supabase.filings_daily
order by day
```

```sql late_filers
select * from supabase.filings_late_filers
where cnpj is not null
order by informes_late desc, max_days_late desc
```

```sql silent_filers
select * from supabase.filings_silent_filers
where cnpj is not null
order by registry_nav_mm desc nulls last, months_silent
```

```sql restatement_screen
select * from supabase.filings_restatement_screen
where cnpj is not null
order by restatements desc
```

```sql restatements_by_type
select * from supabase.filings_restatements_by_type
where tipo_documento is not null
order by restatements desc
```

```sql restatements_latest
select * from supabase.filings_restatements_latest
where fnet_id is not null
order by delivered_at desc, fnet_id desc
```

```sql fidc_diff
select * from supabase.filings_fidc_diff
where fnet_id is not null
order by delivered_at desc, fnet_id desc, field_path
```

# Filing Behaviour

> When funds file, how late, how often they re-file, and which funds stopped
> filing. The documents come from B3's Fundos.NET (FNET) register as SILO holds
> it, and the silence test reads CVM's own monthly and daily datasets.
>
> **These are signals, not findings.** A late delivery is a timestamp compared
> with a rule. A restatement can be a typo fix. A silent fund can be a merger CVM
> has not recorded yet. Each section says what else produces the same row. The
> register is SILO's crawl of FNET, not all of FNET: history before SILO's first
> crawl is partial, and a document is known as a fund's only through its CNPJ
> link, which the per-fund sweep adds every two weeks.

<BigValue data={headline} value=documents title="Documents Delivered, Last 30 Days" fmt=num0/>
<BigValue data={headline} value=restatements title="Restatements, Last 30 Days" fmt=num0/>
<BigValue data={headline} value=restated_share_num1 title="Restated Share (%)" fmt=num1/>
<BigValue data={headline} value=restatements_rc title="Restatements CVM Required" fmt=num0/>
<BigValue data={headline} value=last_delivered_at title="Newest Delivery (São Paulo time)"/>

> The window is <Value data={headline} column=window_from/> to
> <Value data={headline} column=window_to/>. Today is left out because the
> build runs in the morning, while documents are still arriving.

---

## Filings Delivered per Day

> Documents in the register by FNET delivery day over the last 90 complete days,
> first filings (`versao` 1) apart from re-filings (`versao` above 1). The day is
> FNET's own delivery stamp in São Paulo local time. The count covers the FII,
> FIDC and ETF documents SILO crawls. It is not every document FNET holds, and a
> dip can be a crawl gap as easily as a quiet day: check the `fnet` row on
> [Pipeline Ops](/ops) before reading one.

<BarChart
  data={daily}
  x=day
  y={['first_filings','restatements']}
  type=stacked
  yAxisTitle="Documents"
  title="FNET Documents by Delivery Day, Last 90 Days"
/>

---

## Late Filers: Monthly Informe Past the CVM 175 Deadline

> FIIs and FIDCs whose monthly informe first reached FNET at least **5 days**
> after the deadline in at least **2** of the last **12** reference months. The
> deadline is cited, not assumed: Resolução CVM 175 gives 15 days after the end
> of the reference month (FIDC: Anexo Normativo II, art. 27, III; FII: Anexo
> Normativo III, art. 36, I).
>
> **What this screen does not support.** SILO applies no holiday calendar, so a
> deadline on a weekend or holiday may roll forward; the 5-day margin absorbs
> that. Months before 2024-12 (FIDC) and 2025-07 (FII) are not measured, because
> funds had until then to adapt to the resolution. A month with no informe in the
> register is not counted at all; absence is the silent-filer question below. An
> extension CVM granted, or a filing made by other means and uploaded later,
> produces the same row. A fund with several classes is measured on its earliest
> filing.

<DataTable data={late_filers}>
  <Column id=fund_name title="Fund (FNET label)"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=fund_family title="Family"/>
  <Column id=informes title="Months Measured" fmt=num0/>
  <Column id=informes_late title="Months Late" fmt=num0/>
  <Column id=max_days_late title="Worst, Days Past Deadline" fmt=num0/>
  <Column id=median_lag_days_num1 title="Median Days After Month End" fmt=num1/>
  <Column id=last_late_reference title="Last Late Month"/>
</DataTable>

---

## Silent Filers: Active in the Registry, No Informe

> Funds that CVM's registry still lists as active whose last periodic informe in
> CVM's own dataset is **3 to 24 complete months** behind the family's latest
> complete month. FI is read from the informe diário, FIDC, FII and FIAGRO from
> the monthly informe. Silence is counted against the newest month CVM has
> published in full, never today, so an unpublished month does not read as
> silence. Largest registry net assets first.
>
> **What this screen does not support.** FIP files once a year and is not
> screened. The same row comes from a fund merged, incorporated or liquidated
> whose registry status CVM has not updated, from a CVM 175 adaptation that
> moved reporting to a class CNPJ, from CVM's dataset lagging the filing itself,
> or from a SILO ingest gap. If a whole family goes silent at once, check
> [Pipeline Ops](/ops) first. Registry net assets carry the registry's own date.
> A blank FNET column means no FNET document is linked to the CNPJ, not that the
> fund files nowhere.

<DataTable data={silent_filers}>
  <Column id=fund_name title="Fund (registry)"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=fund_family title="Family"/>
  <Column id=registry_status title="Registry Status"/>
  <Column id=last_filed_period title="Last Filed Period"/>
  <Column id=complete_through title="Family Complete Through"/>
  <Column id=months_silent title="Months Silent" fmt=num0/>
  <Column id=reports_filed title="Periods Filed" fmt=num0/>
  <Column id=registry_nav_mm title="Registry Net Assets (R$mm)" fmt=num1/>
  <Column id=registry_nav_date title="Net Assets Date"/>
  <Column id=fnet_last_delivered title="Newest FNET Document"/>
</DataTable>

---

## Frequent Restaters

> Funds with at least **3** re-filings (`versao` above 1) in the last **12**
> months of FNET deliveries that are also at least **20%** of the fund's
> documents in that window. FNET publishes the kind: **RE** is voluntary
> (Reapresentação Espontânea), **RC** is required by CVM (Reapresentação por
> Exigência).
>
> **What this screen does not support.** Only documents linked to the fund's
> CNPJ count, so a recent re-filing the fortnightly sweep has not linked yet is
> missing, as is history before SILO's first crawl. The same row comes from
> routine typo fixes, an administrator or custodian migration that re-submits a
> whole book, the CVM 175 adaptation, a FNET template change, or a CVM sweep
> across one administrator's funds. An RC says CVM asked, not what was wrong.
> Top 50 by re-filings.

<DataTable data={restatement_screen}>
  <Column id=fund_name title="Fund (FNET label)"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=tipo_fundo title="Type"/>
  <Column id=documents title="Documents" fmt=num0/>
  <Column id=restatements title="Re-filings" fmt=num0/>
  <Column id=restatements_re title="Voluntary (RE)" fmt=num0/>
  <Column id=restatements_rc title="CVM Required (RC)" fmt=num0/>
  <Column id=restated_share_num1 title="Re-filed Share (%)" fmt=num1/>
  <Column id=last_restated title="Last Re-filing"/>
</DataTable>

---

## Latest Restatements

> Re-filings delivered in the last 30 complete days, by FNET document type.
> **Linked** is how many carry a fund CNPJ link yet. **Diffed** is how many SILO
> has compared field by field with the version they replaced, which today covers
> the FIDC informe mensal only.

<DataTable data={restatements_by_type}>
  <Column id=tipo_documento title="Document Type"/>
  <Column id=restatements title="Re-filings" fmt=num0/>
  <Column id=restatements_re title="Voluntary (RE)" fmt=num0/>
  <Column id=restatements_rc title="CVM Required (RC)" fmt=num0/>
  <Column id=linked title="Linked to a Fund" fmt=num0/>
  <Column id=diffed title="Diffed" fmt=num0/>
</DataTable>

> The 50 newest re-filings already linked to a fund CNPJ, each with FNET's
> download link. The per-fund sweep runs every two weeks, so the newest
> re-filings are mostly not linked yet. They are counted in the table above and
> left out here; a fund is never inferred from its name. **Diff status** is the
> diff job's verdict on the pair: `compared`, or why not. Blank means the
> document was not considered for a diff, which is every type but the FIDC
> informe mensal.

<DataTable data={restatements_latest} rows=20>
  <Column id=delivered_at title="Delivered (São Paulo time)"/>
  <Column id=fund_name title="Fund (FNET label)"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=tipo_fundo title="Type"/>
  <Column id=tipo_documento title="Document Type"/>
  <Column id=reference_raw title="Reference"/>
  <Column id=versao title="Version"/>
  <Column id=modalidade title="Kind"/>
  <Column id=diff_status title="Diff Status"/>
  <Column id=fields_changed title="Fields Changed" fmt=num0/>
  <Column id=source_url title="Document" contentType=link linkLabel="FNET"/>
</DataTable>

---

## What a FIDC Restatement Changed

> Field by field, for the 10 newest FIDC informe re-filings SILO compared that
> changed at least one field, at most 20 fields each. Old and new values are the
> text as filed, comma decimals included. **Change** is a value changed, added
> or removed. **Delta** is set only on numeric fields.
>
> **What this does not support.** Only the FIDC informe mensal is diffed, and
> only restatements delivered from 2026 on. Tab VIII (debtors) is not in the XML
> FNET serves, so its changes are invisible here. The comparison is between
> FNET's versions, not CVM's CSVs, which CVM republishes in place. A row matched
> by `position` rather than `key` or `path` is approximate by construction. The
> full diff for one fund is `api.fund_restatement_diff`.

<DataTable data={fidc_diff} rows=25>
  <Column id=delivered_at title="Delivered (São Paulo time)"/>
  <Column id=fund_name title="Fund (FNET label)"/>
  <Column id=cnpj title="CNPJ"/>
  <Column id=reference_raw title="Reference"/>
  <Column id=versao title="Version"/>
  <Column id=field_path title="Field"/>
  <Column id=change_kind title="Change"/>
  <Column id=old_value title="Old Value (as filed)"/>
  <Column id=new_value title="New Value (as filed)"/>
  <Column id=delta title="Delta (source units)" fmt='#,##0.00'/>
  <Column id=match_basis title="Matched By"/>
</DataTable>

---

> **An empty table means no fund matched the threshold**, not that the screen
> failed to run. If several sections are empty at once, check whether the FNET
> and CVM slices landed on [Pipeline Ops](/ops) before concluding that every
> fund filed on time.
