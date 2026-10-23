---
title: B3 Options
hide_title: true
sidebar_position: 5
---

<!--
  B3 listed options from the public COTAHIST tape: the call board (tpmerc 070)
  and the put board (080). Exercises print on 012/013 and are excluded.

  Everything here is PREMIUM: COTAHIST VOLTOT, price x quantity of the option
  itself, in R$. It is not notional and not open interest; COTAHIST publishes
  no open interest, so this page shows none.

  Every source is bounded to the last 90 calendar days of OPTION tape,
  relative to the newest option session, not to today. A stalled ingest shows
  as a series that stops, not as a fake decline. The long monthly history is
  the Options Activity section on /markets.

  ZERO-ROW SAFETY: every source appends a NULL row when its window is empty.
-->

```sql options_daily
select * from supabase.options_daily
```

```sql options_last
select *
from supabase.options_daily
where trade_date is not null
order by trade_date desc
limit 1
```

```sql options_top_underlyings
select * from supabase.options_top_underlyings
```

```sql options_expiry_ladder
select * from supabase.options_expiry_ladder
```

# B3 Options

> Listed options on B3, from the public COTAHIST tape: what traded in the last
> 90 days, on which underlying and for which expiry.
>
> All values are **premium**: price × quantity of the option itself, in R$. This
> is **not notional** and **not open interest**; COTAHIST publishes no open
> interest. Exercises print on separate boards and are excluded.
>
> The window ends at the newest option session on the tape, not at today. The
> monthly history since 2019 is on [B3 Markets](/markets).

<BigValue data={options_last} value=trade_date title="Latest Session"/>
<BigValue data={options_last} value=call_premium_mn title="Call Premium (R$mn)" fmt=num0/>
<BigValue data={options_last} value=put_premium_mn title="Put Premium (R$mn)" fmt=num0/>
<BigValue data={options_last} value=put_call_ratio title="Put/Call (premium)" fmt=num2/>
<BigValue data={options_last} value=n_series title="Series Printed" fmt=num0/>

---

## Daily Premium — Last 90 Days

> Premium per session on the call and put boards. A gap is a session with no
> tape ingested, not a session with no trading ([Pipeline Ops](/ops)).

<BarChart
  data={options_daily}
  x=trade_date
  y={['call_premium_mn','put_premium_mn']}
  type=stacked
  yAxisTitle="Premium (R$mn)"
  title="Option Premium per Session — Calls vs Puts (R$mn)"
/>

> **Put/call ratio** is put premium divided by call premium on the same
> session. Above 1 means more R$ changed hands on puts than on calls. It
> compares premium, not contracts, so a few expensive puts can move it.

<LineChart
  data={options_daily}
  x=trade_date
  y=put_call_ratio
  yAxisTitle="Put / Call"
  title="Put/Call Premium Ratio per Session"
/>

---

## Top Underlyings — Last 90 Days

> The 20 underlyings with the most option premium. The underlying is the first
> four letters of the option ticker, which B3 builds from the underlying's
> root (`PETRK350` → `PETR`). Index options (`IBOV`) and ETF options (`BOVA`,
> `SMAL`) are roots too. An index-option premium is in R$ like any other.

<DataTable data={options_top_underlyings} rows=20>
  <Column id=underlying title="Underlying"/>
  <Column id=premium_mn title="Premium 90d (R$mn)" fmt=num0/>
  <Column id=call_premium_mn title="Calls (R$mn)" fmt=num0/>
  <Column id=put_premium_mn title="Puts (R$mn)" fmt=num0/>
  <Column id=put_call_ratio title="Put/Call" fmt=num2/>
  <Column id=last_session_premium_mn title="Last Session (R$mn)" fmt=num1/>
  <Column id=n_series title="Series" fmt=num0/>
  <Column id=n_trades title="Trades" fmt=num0/>
</DataTable>

---

## Premium by Expiry Month

> Premium traded in the 90-day window, grouped by the option's published expiry
> month. Most premium sits in the nearest one or two monthly expiries; an
> option that expired inside the window counts in its own month.

<BarChart
  data={options_expiry_ladder}
  x=expiry_month
  y=premium_mn
  series=side
  type=stacked
  yAxisTitle="Premium (R$mn)"
  title="Option Premium by Expiry Month — Calls vs Puts (R$mn)"
/>
