---
title: B3 Markets
---

<!--
  B3 exchange activity from the public COTAHIST tape (b3_cotahist), 2019 to the
  present. This page is about the EXCHANGE — what printed, in what volume, on
  which board — not about funds; fund NAV/flows stay on their own pages.

  DATA CONVENTIONS the reader must know, stated in the lede:
    * Prices are UNADJUSTED: COTAHIST carries the raw session print, with no
      split or dividend adjustment. A long price series across a corporate
      action is discontinuous by construction.
    * fator_cotacao != 1 papers exist: some instruments quote per lot of 1000,
      so a "price" is not always a per-share price. Volume (price x quantity in
      R$) is comparable across papers; close prices are not always.
    * instrument_type / instrument_subtype / share_class come from
      vw_b3_instrument_typed, classified from CODBDI/ESPECI/TPMERC — never
      guessed from ticker shape. Rows whose board carries no family signal
      classify as NULL subtype and are shown as such.

  NO latest_complete_period() CLAMP anywhere on this page: COTAHIST is session
  prints, complete by construction the day B3 publishes the file — unlike CVM
  filings there is no partially-filed trailing month to hide. Every series is
  bounded by max(trade_date) of the tape itself, so an ingest stall shows as a
  series that stops, not as a fake decline.

  ZERO-ROW SAFETY: every source here is spine-driven (generate_series month
  spine LEFT JOINed to aggregates) or aggregate-single-row, with a union-all
  fallback on the one ranked top-N source — see the source headers.
-->

```sql b3_market_overview
select * from supabase.b3_market_overview
```

```sql b3_monthly_volume
select * from supabase.b3_monthly_volume
```

```sql b3_asset_class_volume
select * from supabase.b3_asset_class_volume
```

```sql b3_fund_quota_split
select period, etf_volume_bn, fii_volume_bn
from supabase.b3_asset_class_volume
where instrument_type = 'fund_quota'
order by period
```

```sql b3_top_volume
select * from supabase.b3_top_volume
```

```sql b3_options_activity
select * from supabase.b3_options_activity
```

# B3 Markets

> The exchange side of the record: every session print on B3's public COTAHIST
> tape since 2019 — cash equities, BDRs, units, listed fund quotas and the
> option boards. This is what actually traded, at what price and in what volume.
>
> Quotes are **unadjusted**, straight from COTAHIST: no split or dividend
> adjustment, so a price series across a corporate action is discontinuous by
> construction, and papers with `fator_cotacao` ≠ 1 quote per lot rather than
> per share. Volume in R$ is comparable across papers; raw close prices are not
> always. Unlike CVM filings, session data has no publication lag to heal — a
> series that stops means the ingest stopped, not that the market did (check
> [Pipeline Ops](/ops)).

<BigValue data={b3_market_overview} value=latest_session label="Latest Session"/>
<BigValue data={b3_market_overview} value=cash_instruments label="Cash Instruments Printed" fmt=num0/>
<BigValue data={b3_market_overview} value=session_volume_bn label="Session Volume (R$bn)" fmt=num1/>
<BigValue data={b3_market_overview} value=option_series label="Option Series Printed" fmt=num0/>

---

## Monthly Traded Volume

> Standard lot (`tpmerc 010`) against the odd-lot boards (`020`/`021`). The
> odd-lot band is small in R$ but is where retail order flow prints; a month
> with a blank band is a month with no tape ingested, not a month with no
> trading.

<AreaChart
data={b3_monthly_volume}
x=period
y={['std_lot_volume_bn','odd_lot_volume_bn']}
type=stacked
yAxisTitle="Volume (R$bn)"
  title="B3 Monthly Traded Volume — Standard vs Odd Lot (R$bn)"
/>

<LineChart
  data={b3_monthly_volume}
  x=period
  y=n_cash_tickers
  yAxisTitle="Distinct Tickers"
  title="Distinct Cash Tickers Printing per Month"
/>

---

## Volume by Instrument Type

> The cash tape split by what the paper is — classified from B3's own
> CODBDI/ESPECI codes, never from ticker shape. `cash_security` is
> exchange-traded debt (debentures, CRI/CRA and similar); `fund_quota` is
> listed fund quotas, split into ETF and FII below.

<AreaChart
  data={b3_asset_class_volume}
  x=period
  y=volume_bn
  series=instrument_type
  type=stacked
  yAxisTitle="Volume (R$bn)"
  title="Standard-Lot Volume by Instrument Type (R$bn)"
/>

> Inside the `fund_quota` band: ETF versus FII exchange volume. A quota row
> whose board carries no family signal counts in the band above but in neither
> line here — the gap is real, not zero.

<LineChart
data={b3_fund_quota_split}
x=period
y={['etf_volume_bn','fii_volume_bn']}
yAxisTitle="Volume (R$bn)"
  title="Listed Fund Quota Volume — ETF vs FII (R$bn)"
/>

---

## Most Traded — Last 90 Days of Tape

> Top 15 tickers by standard-lot volume over the last 90 calendar days the tape
> covers (relative to the tape's own last session, not to today). `Last Close`
> is the raw unadjusted print.

<DataTable data={b3_top_volume} rows=15>
  <Column id=codneg title="Ticker"/>
  <Column id=instrument_type title="Type"/>
  <Column id=share_class title="Class"/>
  <Column id=volume_bn title="Volume 90d (R$bn)" fmt=num2/>
  <Column id=avg_daily_trades title="Avg Daily Trades" fmt=num0/>
  <Column id=last_close title="Last Close (R$)" fmt='#,##0.00'/>
</DataTable>

---

## Options Activity

> Premium traded on the call (`070`) and put (`080`) boards — price × quantity
> of the option itself, not notional exercised; exercises print on separate
> boards and are excluded. Series count is distinct option tickers that printed
> at least once in the month.

<AreaChart
data={b3_options_activity}
x=period
y={['call_volume_bn','put_volume_bn']}
type=stacked
yAxisTitle="Premium (R$bn)"
  title="Option Premium Traded — Calls vs Puts (R$bn)"
/>

<LineChart
  data={b3_options_activity}
  x=period
  y=n_series
  yAxisTitle="Series"
  title="Option Series Traded per Month"
/>
