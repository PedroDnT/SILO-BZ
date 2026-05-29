---
title: Suspicious Deal Screens
---

```sql zombie_growth
select
  a.cnpj,
  coalesce(r.fund_name, a.cnpj) as fund_name,
  a.period,
  m.vl_patrim_liq / 1e6 as pl_mm,
  round(100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0), 1) as inad_pct
from cvm_fidc_aging a
join cvm_fidc_mensal m using (cnpj, period)
left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
where a.period = (select max(period) from cvm_fidc_aging)
  and m.vl_patrim_liq > 1e6
  and 100.0 * a.vl_total_inad / nullif(m.vl_patrim_liq, 0) > 5
order by pl_mm desc nulls last
limit 20
```

```sql captive_vehicles
select
  m.cnpj,
  coalesce(max(r.fund_name), m.cnpj) as fund_name,
  max(m.period) as latest_period,
  max(m.vl_patrim_liq) / 1e6 as pl_mm,
  min(m.nr_cotst) as min_investors
from cvm_fii_mensal m
left join cvm_fund_registry r on r.cnpj = m.cnpj and r.entity_type = 'fii'
where m.doc_subtype = 'complemento'
  and m.period >= current_date - interval '3 months'
group by m.cnpj
having min(m.nr_cotst) < 10 and max(m.vl_patrim_liq) > 5e7
order by pl_mm desc nulls last
limit 20
```

```sql evergreen_aging
select
  a.cnpj,
  coalesce(max(r.fund_name), a.cnpj) as fund_name,
  count(distinct a.period) as months_observed,
  min(round(100.0 * a.vl_inad_maior_1080 / nullif(a.vl_total_inad, 0), 1)) as min_longtail_pct,
  max(round(100.0 * a.vl_inad_maior_1080 / nullif(a.vl_total_inad, 0), 1)) as max_longtail_pct
from cvm_fidc_aging a
left join cvm_fund_registry r on r.cnpj = a.cnpj and r.entity_type = 'fidc'
where a.period >= current_date - interval '12 months'
  and a.vl_total_inad > 1e5
group by a.cnpj
having max(round(100.0 * a.vl_inad_maior_1080 / nullif(a.vl_total_inad, 0), 1)) > 70
   and max(round(100.0 * a.vl_inad_maior_1080 / nullif(a.vl_total_inad, 0), 1))
     - min(round(100.0 * a.vl_inad_maior_1080 / nullif(a.vl_total_inad, 0), 1)) < 10
order by max_longtail_pct desc nulls last
limit 20
```

```sql overdue_securit
select
  s.instrument_type,
  s.cnpj_securit,
  s.codigo_identificacao,
  s.data_vencimento,
  s.situacao,
  s.valor_total_integralizado / 1e6 as volume_mm,
  s.classificacao_risco_atual as rating
from cvm_securit_serie s
where s.data_vencimento < current_date
  and s.situacao not in ('Cancelado','Vencido','Liquidado','Encerrado')
  and s.valor_total_integralizado > 1e5
order by s.data_vencimento asc
limit 30
```

# Suspicious Deal Screens

Forensic patterns that can obscure financial health. These are signals — always verify with primary sources.

---

## 🧟 Zombie Growth — Delinquency > 5% with Meaningful AUM

> FIDCs with elevated delinquency still carrying large portfolios. New money may be masking embedded losses.

<DataTable data={zombie_growth}>
  <Column id=fund_name title="Fund"/>
  <Column id=period title="Period"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=inad_pct title="Delinq %" fmt=num1/>
</DataTable>

---

## 🔒 Captive Vehicles — High AUM, Almost No Investors

> FIIs with > R$50mm AUM but fewer than 10 investors. Single-LP structures.

<DataTable data={captive_vehicles}>
  <Column id=fund_name title="Fund"/>
  <Column id=latest_period title="Period"/>
  <Column id=pl_mm title="AUM (R$mm)" fmt=num1/>
  <Column id=min_investors title="Min Investors" fmt=num0/>
</DataTable>

---

## 🌿 Evergreen Aging — Credits Stuck in 1080+ Day Bucket

> FIDCs where long-tail delinquency (>1080d) stays above 70% and barely moves. Credits are being rolled, not resolved.

<DataTable data={evergreen_aging}>
  <Column id=fund_name title="Fund"/>
  <Column id=months_observed title="Months"/>
  <Column id=min_longtail_pct title="Long-tail % Min" fmt=num1/>
  <Column id=max_longtail_pct title="Long-tail % Max" fmt=num1/>
</DataTable>

---

## ⏰ Overdue Securit Series — Still Active Past Maturity

> CRA/CRI/OTS series past their maturity date but not marked as vencido/cancelado.

<DataTable data={overdue_securit}>
  <Column id=instrument_type title="Type"/>
  <Column id=codigo_identificacao title="Code"/>
  <Column id=data_vencimento title="Maturity"/>
  <Column id=situacao title="Status"/>
  <Column id=volume_mm title="Volume (R$mm)" fmt=num1/>
  <Column id=rating title="Rating"/>
</DataTable>
