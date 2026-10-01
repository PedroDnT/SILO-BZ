---
title: Fund Holdings
hide_title: true
sidebar_position: 14
---

<!--
  What investment funds hold, from CVM's monthly portfolio filings (CDA):

    mv_fund_holdings_monthly   analytical file 30, rebuilt by every analytical
                               apply from cvm_fi_cda_acoes (CDA block 4) and
                               cvm_fi_cda_cotas (block 2), 2019 on.
                                 kind 'stock'      key = B3 ticker: shares,
                                                   shares lent out, units
                                 kind 'debenture'  key = issuer's B3 code,
                                                   characters 3-6 of the ISIN
                                 kind 'quota'      month totals only
                               A key NULL row is the month's total for its kind.

  COMPLETENESS: CVM's newest CDA months fill in late (issue #476: from 2026-06
  about half the funds). Every figure ends at each kind's last complete month,
  the last one whose filing funds reach 90% of the median of the 12 months
  before it (holdings_monthly.sql, holdings_top.sql). The month is shown.

  SAME GROUP: emissor_ligado = 'S' is CVM's flag that the asset's issuer is in
  the fund's own economic group. For fund quotas that is mostly feeder funds
  holding their own manager's master fund, an ordinary structure.

  ZERO-ROW RULE: both sources LEFT JOIN onto a one-row driver.
-->

```sql holdings_monthly
select * from supabase.holdings_monthly
```

```sql stock_latest
select n_funds, n_assets, total_bn, related_bn, period
from supabase.holdings_monthly
where kind = 'stock' and period = p_end
```

```sql debenture_latest
select n_funds, n_assets, total_bn, period
from supabase.holdings_monthly
where kind = 'debenture' and period = p_end
```

```sql quota_latest
select total_bn, related_bn, related_share_num2 * 100 as related_pct_num1, period
from supabase.holdings_monthly
where kind = 'quota' and period = p_end
```

```sql holdings_trend
select period,
       case kind when 'stock' then 'Stocks' else 'Debentures' end as kind,
       total_bn
from supabase.holdings_monthly
where kind in ('stock', 'debenture') and complete
order by kind, period
```

```sql quota_related_trend
select period, related_share_num2 * 100 as related_pct_num1
from supabase.holdings_monthly
where kind = 'quota' and complete
order by period
```

```sql stock_top
select key as ticker, n_funds, held_bn, held_12m_ago_bn,
       (held_bn / nullif(held_12m_ago_bn, 0) - 1) * 100 as change_12m_pct_num1,
       related_bn, period
from supabase.holdings_top
where grain = 'stock'
order by rk
```

```sql stock_top15
select key as ticker, held_bn
from supabase.holdings_top
where grain = 'stock' and rk <= 15
order by rk
```

```sql stock_related
select key as ticker, related_bn, held_bn,
       related_bn / nullif(held_bn, 0) * 100 as related_pct_num1, period
from supabase.holdings_top
where grain = 'stock_related'
order by rk
```

```sql debenture_top
select key as issuer_code, n_funds, n_assets, held_bn, held_12m_ago_bn,
       (held_bn / nullif(held_12m_ago_bn, 0) - 1) * 100 as change_12m_pct_num1,
       period
from supabase.holdings_top
where grain = 'debenture'
order by rk
```

# Fund Holdings

> What Brazilian investment funds hold, by stock and by debenture issuer.
> Source: CVM's monthly portfolio filings (CDA), as each fund filed them, market
> value at the end of the month. CVM publishes a month with a delay, and late
> filers keep arriving for months after, so every figure ends at the last month
> in which nearly all funds have filed (shown on each tile and table). Rebuilt
> by the nightly analytical run.

<BigValue data={stock_latest} value=total_bn title="Stocks Held (R$ bn)" fmt=num1/>
<BigValue data={stock_latest} value=n_assets title="Tickers"/>
<BigValue data={debenture_latest} value=total_bn title="Debentures Held (R$ bn)" fmt=num1/>
<BigValue data={debenture_latest} value=n_assets title="Debenture Issuers"/>
<BigValue data={stock_latest} value=period title="Month"/>

---

## Stocks Funds Hold the Most

> Shares, shares lent out and units, by B3 ticker, at market value on the last
> complete month. Borrowed shares (a liability), options, futures and BDRs are
> left out. The 12-month change mixes price moves with buying and selling.

<BarChart
  data={stock_top15}
  x=ticker
  y=held_bn
  swapXY=true
  sort=false
  yAxisTitle="R$ bn"
  title="15 Largest Stock Holdings by Funds"
/>

<DataTable data={stock_top} rows=25>
  <Column id=ticker title="Ticker"/>
  <Column id=n_funds title="Funds Holding"/>
  <Column id=held_bn title="Held (R$ bn)" fmt=num2/>
  <Column id=held_12m_ago_bn title="12 Months Earlier (R$ bn)" fmt=num2/>
  <Column id=change_12m_pct_num1 title="Change (%)" fmt=num1/>
  <Column id=period title="Month"/>
</DataTable>

---

## Stocks and Debentures Over Time

> Total market value funds hold each month since 2019, complete months only.

<LineChart
  data={holdings_trend}
  x=period
  y=total_bn
  series=kind
  yAxisTitle="R$ bn"
  title="Stocks and Debentures Held by Funds"
/>

---

## Debentures by Issuer

> Debentures grouped by the issuer's B3 code, the four letters after "BR" in the
> ISIN (BRTAEEDBS0O9 is TAEE). No company name is attached: the code is what the
> filing carries. A company can issue under more than one code.

<DataTable data={debenture_top} rows=25>
  <Column id=issuer_code title="Issuer Code"/>
  <Column id=n_funds title="Funds Holding"/>
  <Column id=n_assets title="Debenture Codes"/>
  <Column id=held_bn title="Held (R$ bn)" fmt=num2/>
  <Column id=held_12m_ago_bn title="12 Months Earlier (R$ bn)" fmt=num2/>
  <Column id=change_12m_pct_num1 title="Change (%)" fmt=num1/>
  <Column id=period title="Month"/>
</DataTable>

---

## Holdings Inside the Same Economic Group

> CVM's filing flags an asset whose issuer belongs to the fund's own economic
> group. For stocks, that is a fund holding shares of a company in its manager's
> group. For fund quotas it is mostly feeder funds holding their own manager's
> master fund, which is how most Brazilian funds are built, so a high share is
> normal there.

<DataTable data={stock_related} rows=15>
  <Column id=ticker title="Ticker"/>
  <Column id=related_bn title="Held by Same-Group Funds (R$ bn)" fmt=num2/>
  <Column id=held_bn title="Held by All Funds (R$ bn)" fmt=num2/>
  <Column id=related_pct_num1 title="Same-Group Share (%)" fmt=num1/>
  <Column id=period title="Month"/>
</DataTable>

<BigValue data={quota_latest} value=related_pct_num1 title="Fund Quotas in Same-Group Funds (%)" fmt=num1/>
<BigValue data={quota_latest} value=total_bn title="Fund Quotas Held (R$ bn)" fmt=num1/>
<BigValue data={quota_latest} value=period title="Month"/>

<LineChart
  data={quota_related_trend}
  x=period
  y=related_pct_num1
  yAxisTitle="%"
  title="Share of Fund Quotas Held in Same-Group Funds"
/>
