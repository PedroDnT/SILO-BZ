---
title: Financials — ITR/DFP Statements
---

```sql financials
with latest as (
  select cd_cvm, max(dt_refer) as dt_refer
  from cia_account where grupo = 'DRE' and escopo = 'con'
  group by cd_cvm
),
dre as (
  select
    a.cd_cvm,
    a.dt_refer,
    max(a.vl_conta) filter (where a.cd_conta = '3.01') / 1e6 as receita_mm,
    max(a.vl_conta) filter (where a.cd_conta = '3.03') / 1e6 as resultado_bruto_mm,
    coalesce(
      max(a.vl_conta) filter (where a.cd_conta = '3.11'),
      max(a.vl_conta) filter (where a.cd_conta = '3.09')
    ) / 1e6 as lucro_mm
  from cia_account a
  join latest l on l.cd_cvm = a.cd_cvm and l.dt_refer = a.dt_refer
  where a.grupo = 'DRE' and a.escopo = 'con' and a.ordem_exerc = 'ÚLTIMO'
  group by a.cd_cvm, a.dt_refer
),
balance as (
  select
    a.cd_cvm,
    max(a.vl_conta) filter (where a.grupo = 'BPA' and a.cd_conta = '1') / 1e6 as ativo_total_mm,
    max(a.vl_conta) filter (where a.grupo = 'BPP' and a.ds_conta = 'Patrimônio Líquido Consolidado') / 1e6 as pl_mm
  from cia_account a
  join latest l on l.cd_cvm = a.cd_cvm and l.dt_refer = a.dt_refer
  where a.grupo in ('BPA', 'BPP') and a.escopo = 'con' and a.ordem_exerc = 'ÚLTIMO'
  group by a.cd_cvm
)
select
  c.denom_cia as company,
  coalesce(c.setor, 'Não informado') as setor,
  d.dt_refer as ref_date,
  d.receita_mm,
  d.lucro_mm,
  case when d.receita_mm > 0 then round(100.0 * d.lucro_mm / d.receita_mm, 1) end as net_margin_pct,
  b.ativo_total_mm,
  b.pl_mm,
  case when b.pl_mm > 0 then round(100.0 * d.lucro_mm / b.pl_mm, 1) end as roe_pct
from dre d
join cia_company c on c.cd_cvm = d.cd_cvm
left join balance b on b.cd_cvm = d.cd_cvm
where d.receita_mm is not null
order by d.receita_mm desc nulls last
```

```sql margin_by_setor
select
  setor,
  count(*) as companies,
  round(avg(net_margin_pct), 1) as avg_net_margin_pct,
  round(avg(roe_pct), 1) as avg_roe_pct
from ${financials}
where net_margin_pct is not null
  and net_margin_pct between -100 and 100
group by setor
having count(*) >= 5
order by avg_net_margin_pct desc
```

# Financials — Consolidated Statements

> Latest consolidated ITR/DFP per company (escopo `con`, exercise `ÚLTIMO`),
> R$ millions. Net income uses conta 3.11 with 3.09 as the fallback used by
> banks; equity is `Patrimônio Líquido Consolidado` (the code varies between
> 2.03 and 2.08 across chart layouts, so it is matched by name). Margins are
> shown only where revenue is positive — quarterly figures, not annualized.

## Profitability by Sector

Sectors with at least 5 reporting companies; margins clipped to ±100% to keep
distressed outliers from drowning the average.

<DataTable data={margin_by_setor}>
  <Column id=setor title="Sector"/>
  <Column id=companies title="Cias" fmt=num0/>
  <Column id=avg_net_margin_pct title="Avg Net Margin %" fmt=num1/>
  <Column id=avg_roe_pct title="Avg ROE % (qtr)" fmt=num1/>
</DataTable>

---

## Company Explorer

All companies with a consolidated DRE, ranked by revenue. Search by name or
sector.

<DataTable data={financials} rows=25 search=true>
  <Column id=company title="Company"/>
  <Column id=setor title="Sector"/>
  <Column id=ref_date title="Ref"/>
  <Column id=receita_mm title="Revenue (R$mm)" fmt=num0/>
  <Column id=lucro_mm title="Net Income (R$mm)" fmt=num0/>
  <Column id=net_margin_pct title="Net Margin %" fmt=num1/>
  <Column id=ativo_total_mm title="Assets (R$mm)" fmt=num0/>
  <Column id=pl_mm title="Equity (R$mm)" fmt=num0/>
  <Column id=roe_pct title="ROE % (qtr)" fmt=num1/>
</DataTable>
