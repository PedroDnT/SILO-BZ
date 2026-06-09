---
title: Corporate Events — IPE Filings
---

```sql by_categoria
select
  categoria,
  count(*) as filings
from cia_event
group by categoria
order by filings desc
limit 12
```

```sql monthly_volume
select
  date_trunc('month', data_entrega)::date as month,
  count(*) as filings,
  count(*) filter (where categoria = 'Fato Relevante') as fatos_relevantes
from cia_event
where data_entrega is not null
group by 1
order by 1
```

```sql fatos
select
  e.data_entrega::date as delivered,
  c.denom_cia as company,
  e.assunto as subject,
  e.link_download
from cia_event e
join cia_company c on c.cd_cvm = e.cd_cvm
where e.categoria = 'Fato Relevante'
order by e.data_entrega desc
limit 200
```

# Corporate Events (IPE)

> Structured event filings — Fatos Relevantes, assembleias, comunicados — as
> disclosed to CVM. `link_download` goes to the primary document on
> rad.cvm.gov.br.

## Filing Volume by Month

<BarChart
  data={monthly_volume}
  x=month
  y={["filings", "fatos_relevantes"]}
  title="IPE filings per month (all categories vs Fatos Relevantes)"
/>

## Filings by Category

<BarChart
  data={by_categoria}
  x=categoria
  y=filings
  swapXY=true
  title="Top categories"
/>

---

## Fato Relevante Feed

The 200 most recent material-fact disclosures. Search by company or subject.

<DataTable data={fatos} rows=25 search=true>
  <Column id=delivered title="Delivered"/>
  <Column id=company title="Company"/>
  <Column id=subject title="Subject" wrap=true/>
  <Column id=link_download title="Doc" contentType=link linkLabel="CVM ↗"/>
</DataTable>
