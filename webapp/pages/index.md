---
title: CIA Aberta — Listed Company Analytics
---

```sql universe
select 'Active companies' as metric, count(*) as n from cia_company where situacao = 'ATIVO'
union all select 'Filings (ITR/DFP/IPE)', count(*) from cia_filing
union all select 'Statement line items', count(*) from cia_account
union all select 'Corporate events', count(*) from cia_event
```

```sql by_setor
select
  coalesce(setor, 'Não informado') as setor,
  count(*) as companies
from cia_company
where situacao = 'ATIVO'
group by 1
order by companies desc
limit 12
```

```sql top_revenue
with latest as (
  select cd_cvm, max(dt_refer) as dt_refer
  from cia_account where grupo = 'DRE' and escopo = 'con'
  group by cd_cvm
)
select
  c.denom_cia as company,
  a.dt_refer as ref_date,
  max(a.vl_conta) filter (where a.cd_conta = '3.01') / 1e6 as receita_mm,
  coalesce(
    max(a.vl_conta) filter (where a.cd_conta = '3.11'),
    max(a.vl_conta) filter (where a.cd_conta = '3.09')
  ) / 1e6 as lucro_mm
from cia_account a
join latest l on l.cd_cvm = a.cd_cvm and l.dt_refer = a.dt_refer
join cia_company c on c.cd_cvm = a.cd_cvm
where a.grupo = 'DRE' and a.escopo = 'con' and a.ordem_exerc = 'ÚLTIMO'
  and a.cd_conta in ('3.01', '3.09', '3.11')
group by c.denom_cia, a.dt_refer
order by receita_mm desc nulls last
limit 15
```

```sql recent_fatos
select
  data_entrega::date as delivered,
  c.denom_cia as company,
  e.assunto as subject
from cia_event e
join cia_company c on c.cd_cvm = e.cd_cvm
where e.categoria = 'Fato Relevante'
order by e.data_entrega desc
limit 15
```

# CIA Aberta — Listed Companies

> CVM open data on Brazilian listed companies: registry, ITR/DFP financial
> statements, and corporate event filings. Same Supabase database as the fund
> dashboard; updated by the daily ingest.

<BigValue data={universe} value=n label=metric fmt=num0/>

---

## Active Companies by Sector

<BarChart
  data={by_setor}
  x=setor
  y=companies
  swapXY=true
  title="Active registrants by CVM sector"
/>

---

## Largest Companies — Latest Quarter (Consolidated DRE)

Revenue (conta 3.01) and net income (3.11, falling back to 3.09 for banks),
R$ millions, latest reference date filed per company.

<DataTable data={top_revenue} rows=15>
  <Column id=company title="Company"/>
  <Column id=ref_date title="Ref Date"/>
  <Column id=receita_mm title="Revenue (R$mm)" fmt=num0/>
  <Column id=lucro_mm title="Net Income (R$mm)" fmt=num0/>
</DataTable>

[Full financials explorer →](/financials)

---

## Latest Fatos Relevantes

<DataTable data={recent_fatos} rows=15>
  <Column id=delivered title="Delivered"/>
  <Column id=company title="Company"/>
  <Column id=subject title="Subject" wrap=true/>
</DataTable>

[All corporate events →](/events)
