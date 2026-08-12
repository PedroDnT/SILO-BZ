---
title: Suspicious Deal Screens
---

<!-- These screens are defined once as RPC functions in
     src/store/analytical/15_fraud_screens.sql so the dashboard and the
     analytical layer share a single definition. -->

```sql zombie_growth
select * from supabase.zombie_growth
```

```sql captive_vehicles
select * from supabase.captive_vehicles
```

```sql evergreen_aging
select * from supabase.evergreen_aging
```

```sql overdue_securit
select * from supabase.overdue_securit
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
