---
title: Suspicious Deal Screens
---

<!--
  These screens are defined once as RPC functions in
  src/store/analytical/15_fraud_screens.sql so the dashboard and the analytical
  layer share a single definition.

  THRESHOLDS ARE ARGUMENTS, not findings, and they are stated on the page so a
  reader can see where each line was drawn:
    fraud_screen_zombie_growth(null, 5, 1e6)        delinquency > 5%, PL > R$1mm
    fraud_screen_evergreen_aging(12, 70, 10)        >1080d bucket ≥ 70%, 12 months
    fraud_screen_overdue_securit(1e5)               volume > R$100k
    fraud_screen_captive_vehicles(3, 10, 5e7)       < 10 investors, PL > R$50mm

  SECTION ORDER groups the two FIDC credit screens first (they read the same
  aging table and compound each other), then the securitisation screen, then the
  FII structural screen. Each links back to the page where the underlying series
  lives, so a hit can be checked in context rather than in isolation.

  THIS PAGE OWNS THE ZOMBIE-GROWTH SCREEN. /fidc previously carried an equivalent
  "delinquency > 5% and AUM > R$1mm" table built from raw SQL
  (high_delinq_growing.sql); it has been removed there in favour of a link, so
  the screen has exactly one definition on the site.
-->

```sql zombie_growth
select * from supabase.zombie_growth
```

```sql evergreen_aging
select * from supabase.evergreen_aging
```

```sql overdue_securit
select * from supabase.overdue_securit
```

```sql captive_vehicles
select * from supabase.captive_vehicles
```

# Suspicious Deal Screens

> Four patterns that can obscure financial health, applied mechanically to every
> fund and series in the warehouse. They are worth looking at because each one is
> a structure that keeps reported numbers stable while the underlying position
> deteriorates.
>
> **These are signals, not findings.** A screen hit is a fund that matches a
> threshold — nothing more. Every pattern here has innocent explanations: a
> concentrated FII may be a legitimate single-asset mandate, a long-dated
> receivable may be performing on its own contractual schedule, and a series past
> maturity may simply be awaiting a filing. Nothing on this page asserts
> wrongdoing, and no hit should be published without checking the fund's own
> reports and CVM filings. The thresholds are stated with each screen so the
> reader can see where the line was drawn and move it themselves.

---

## Zombie Growth — Delinquency Above 5% with Meaningful Net Assets

> FIDCs whose overdue balance exceeds **5% of net assets** while they still carry
> more than **R$1mm**. The concern is a book where new subscriptions arrive faster
> than embedded losses are recognised, so the delinquency ratio stays survivable
> while the absolute loss grows.
>
> The screen is a snapshot at the latest period and says nothing about the
> direction of travel. Read it against the sector trend and the fund-level
> delinquency ranking on [the FIDC Credit Monitor](/fidc), and against the
> subscription flows in the same place — inflows rising into a deteriorating book
> is the combination that gives the pattern its name.

<DataTable data={zombie_growth}>
  <Column id=fund_name title="Fund"/>
  <Column id=period title="Period"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=inad_num1 title="Delinquency (%)" fmt=num1/>
</DataTable>

---

## Evergreen Aging — Credits Stuck in the 1080d+ Bucket

> FIDCs where the share of overdue balance sitting in the **over-1080-day** bucket
> stays at or above **70%** across at least **12 observed months**, and barely
> moves. A receivable more than three years past due that is neither recovered nor
> written off is being rolled, and the aging table is the only place that shows it.
>
> `Long-tail % Min` and `Max` are the range across the observed window: a narrow
> band is the finding — it means the balance is static, not merely large. The full
> bucket-by-bucket profile behind this is on
> [the FIDC Credit Monitor](/fidc).

<DataTable data={evergreen_aging}>
  <Column id=fund_name title="Fund"/>
  <Column id=months_observed title="Months Observed" fmt=num0/>
  <Column id=min_longtail_num1 title="Long-Tail Share, Min (%)" fmt=num1/>
  <Column id=max_longtail_num1 title="Long-Tail Share, Max (%)" fmt=num1/>
</DataTable>

---

## Overdue Securitisation Series — Still Active Past Maturity

> CRI / CRA / OTS series whose maturity date has passed but whose filed `situacao`
> is still not `vencido` or `cancelado`, with more than **R$100k** outstanding.
> Either the series has not been settled or the status has not been updated —
> both are worth knowing, and the filing does not distinguish them.
>
> A stale status is the mundane explanation and is common. The maturity wall these
> series fall off the end of is on [Securitization](/securit), which also counts
> how many series were filed with **no maturity date at all**.

<DataTable data={overdue_securit}>
  <Column id=instrument_type title="Type"/>
  <Column id=codigo_identificacao title="Series Code"/>
  <Column id=data_vencimento title="Maturity"/>
  <Column id=situacao title="Status"/>
  <Column id=volume_mm title="Volume (R$mm)" fmt=num1/>
  <Column id=rating title="Rating (as filed)"/>
</DataTable>

---

## Captive Vehicles — Large Net Assets, Almost No Investors

> FIIs holding more than **R$50mm** with fewer than **10** quotaholders across at
> least **3** observed periods. A publicly registered fund with a handful of
> holders is functionally a private structure using a public wrapper, which
> matters because the disclosure regime it files under assumes dispersed investors.
>
> Single-investor mandates are entirely legal and often deliberate. The FI-side
> equivalent — funds whose _largest_ holder owns most of the net assets — is the
> concentration screen on [FI Industry](/fi); the asset-side equivalent, a fund
> whose net assets are one building, is flagged in the property explorer on
> [FII Market](/fii).

<DataTable data={captive_vehicles}>
  <Column id=fund_name title="Fund"/>
  <Column id=latest_period title="Period"/>
  <Column id=pl_mm title="Net Assets (R$mm)" fmt=num1/>
  <Column id=min_investors title="Min Quotaholders" fmt=num0/>
</DataTable>

---

> **An empty table means no fund matched the threshold at the latest period** —
> not that the screen failed to run. If several screens are empty at once, check
> whether the underlying slices actually landed on [Pipeline Ops](/ops) before
> concluding the market is clean.
