---
title: Recent Data
hide_title: true
sidebar_position: 20
---

<!--
  Reader-facing freshness: the newest data per dataset, read from
  api.coverage(), the same contract the public API serves.

  Two questions are shown side by side and never merged into one verdict
  (AGENTS.md, "Do not confuse OUR health with the SOURCE's"):
    * Landed: when our ingest last succeeded. That is ours.
    * Data Through / Complete Through: how far the source has published. That
      is the source's filing calendar.
  No red/green flag: cadences differ per source, and one threshold would flag
  normal lags. Operator verdicts are on /ops.

  ZERO-ROW SAFETY: coverage() returns fixed literal rows; the source also
  appends a NULL row if it ever returns none.
-->

```sql build_brt
select strftime(built_at - interval 3 hour, '%Y-%m-%d %H:%M') as built_at_brt
from supabase.build_stamp
```

```sql recent_data
select * from supabase.recent_data
```

```sql recent_daily
select *
from supabase.recent_data
where dataset is not null
  and days_behind <= 7
order by as_of desc, dataset
```

```sql recent_counts
select
  count(*)                                         as n_datasets,
  count(*) filter (where days_since_landed <= 1.5) as n_landed_24h,
  max(landed_at_brt)                               as last_landed_brt
from supabase.recent_data
where dataset is not null
```

# Recent Data

> The newest data SILO holds for each dataset, from `api.coverage()`, the same
> freshness record the API serves. Each row answers two different questions:
>
> - **Landed (UTC-3)**: when our ingest last succeeded for that source. An old
>   date here is a pipeline question; see [Pipeline Ops](/ops).
> - **Data Through**: the newest period the source has published and that has
>   already passed. **Complete Through** is the newest **complete** period,
>   which is what the API's default windows serve. CVM publishes monthly data 1
>   to 2 months in arrears and FIP files yearly, so an older date here is
>   usually the filing calendar, not an outage.
>
> Day counts are measured when this snapshot was built.

<BigValue data={build_brt} value=built_at_brt title="Snapshot Built (UTC-3)"/>
<BigValue data={recent_counts} value=n_datasets title="Datasets" fmt=num0/>
<BigValue data={recent_counts} value=n_landed_24h title="Landed in Last ~36h" fmt=num0/>
<BigValue data={recent_counts} value=last_landed_brt title="Last Landing (UTC-3)"/>

---

## Updated This Week

> Datasets whose data reaches within 7 days of the snapshot: the B3 tape,
> lending and flows, BACEN series, the FNET register and the daily fund
> register.

<DataTable data={recent_daily} rows=all>
  <Column id=dataset title="Dataset"/>
  <Column id=source title="Source"/>
  <Column id=as_of title="Data Through"/>
  <Column id=landed_at_brt title="Landed (UTC-3)"/>
</DataTable>

---

## Every Dataset

> Grouped by source. `Days Behind` is the snapshot date minus `Data Through`;
> `Days Since Landed` is the time since our last successful ingest for that
> source. A blank `Complete Through` means the dataset has no completeness
> rule (filings and events arrive one by one), not that it is empty. The
> `Notes` column carries the caveats each date cannot.

<DataTable data={recent_data} rows=all search=true>
  <Column id=dataset title="Dataset"/>
  <Column id=source title="Source"/>
  <Column id=as_of title="Data Through"/>
  <Column id=complete_through title="Complete Through"/>
  <Column id=days_behind title="Days Behind" fmt=num0/>
  <Column id=landed_at_brt title="Landed (UTC-3)"/>
  <Column id=days_since_landed title="Days Since Landed" fmt=num1/>
  <Column id=notes title="Notes" wrap=true/>
</DataTable>
