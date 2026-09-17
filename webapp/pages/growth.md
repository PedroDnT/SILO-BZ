---
title: Growth & Profitability — Within Sector
---

```sql companies
select * from supabase.cia_growth_company
```

```sql sectors
select * from supabase.cia_growth_sector
```

```sql coverage
select
  count(*) as companies_compared,
  max(fy) as fiscal_year,
  count(distinct case when peers_in_setor is not null then setor end) as sectors_with_peers
from supabase.cia_growth_company
```

```sql leaders
select
  company, setor, fy, revenue_mm, rev_growth_pct, net_margin_pct,
  setor_median_growth_pct, vs_setor_pp, rank_in_setor, peers_in_setor
from supabase.cia_growth_company
where rank_in_setor <= 3 and vs_setor_pp is not null
order by vs_setor_pp desc
limit 40
```

```sql movers
select company, setor, revenue_mm, net_margin_pct, margin_change_pp
from supabase.cia_growth_company
where margin_change_pp is not null
order by abs(margin_change_pp) desc
limit 20
```

```sql quadrant
select company, setor, revenue_mm, rev_growth_pct, net_margin_pct
from supabase.cia_growth_company
where rev_growth_pct between -80 and 200
  and net_margin_pct between -60 and 80
```

# Growth & Profitability

Year-over-year revenue growth and margin movement for listed companies, **ranked
within CVM sector**. Every figure compares one annual (DFP) statement against the
immediately preceding one.

<BigValue data={coverage} value=companies_compared title="Companies compared" fmt=num0/>
<BigValue data={coverage} value=fiscal_year title="Fiscal year"/>
<BigValue data={coverage} value=sectors_with_peers title="Sectors with ≥5 peers" fmt=num0/>

<Alert status=warning>

**Revenue is never ranked across sectors here.** Conta `3.01` is sales for an
industrial company and interest income for a bank — not the same quantity. So every
table ranks inside a sector and shows that sector's median beside the company, and
the sector itself is the unit of comparison.

</Alert>

---

## Median Revenue Growth by Sector

Which sectors actually grew. Median rather than mean, so a single outlier does not
move the sector; only sectors with at least five comparable companies appear.

<BarChart
  data={sectors}
  x=setor
  y=median_growth_pct
  swapXY=true
  title="Median YoY revenue growth by CVM sector (%)"
  xAxisTitle="Sector"
  yAxisTitle="Median YoY growth (%)"
/>

<DataTable data={sectors} rows=15>
  <Column id=setor title="Sector"/>
  <Column id=peers title="Peers" fmt=num0/>
  <Column id=median_growth_pct title="Median growth %" fmt=num1/>
  <Column id=median_margin_pct title="Median margin %" fmt=num1/>
  <Column id=sector_revenue_mm title="Sector revenue (R$mm)" fmt=num0/>
</DataTable>

---

## Fastest Growing — Top 3 in Each Sector

`vs sector` is the company's growth minus its sector's median, in percentage points.
It is the column that survives a sector-wide boom: 40% growth in a sector whose
median is 38% is not a growth story.

<DataTable data={leaders} rows=20 search=true>
  <Column id=company title="Company"/>
  <Column id=setor title="Sector"/>
  <Column id=revenue_mm title="Revenue (R$mm)" fmt=num0/>
  <Column id=rev_growth_pct title="YoY growth %" fmt=num1/>
  <Column id=setor_median_growth_pct title="Sector median %" fmt=num1/>
  <Column id=vs_setor_pp title="vs sector (pp)" fmt=num1/>
  <Column id=rank_in_setor title="Rank" fmt=num0/>
  <Column id=peers_in_setor title="of" fmt=num0/>
  <Column id=net_margin_pct title="Net margin %" fmt=num1/>
</DataTable>

---

## Growth vs Profitability

Each dot is a company in the latest fiscal year, sized by revenue: growth on the
horizontal, net margin on the vertical. Top-right is growing and profitable;
bottom-right is buying growth at a loss. The view is clipped to ±200% growth and
±80% margin so a handful of extremes does not compress the readable cloud — clipped
companies still appear in the tables above.

<ScatterPlot
  data={quadrant}
  x=rev_growth_pct
  y=net_margin_pct
  size=revenue_mm
  tooltipTitle=company
  xAxisTitle="YoY revenue growth (%)"
  yAxisTitle="Net margin (%)"
  title="Growth vs margin, latest fiscal year"
/>

---

## Biggest Margin Moves

Net margin change in percentage points against the prior year — expansion and
compression together, largest absolute move first. A margin move is often the
earlier signal: revenue growth with collapsing margin is a different story from
revenue growth without it.

<DataTable data={movers} rows=20>
  <Column id=company title="Company"/>
  <Column id=setor title="Sector"/>
  <Column id=revenue_mm title="Revenue (R$mm)" fmt=num0/>
  <Column id=net_margin_pct title="Net margin %" fmt=num1/>
  <Column id=margin_change_pp title="Change (pp)" fmt=num1/>
</DataTable>

---

## How to read this page

Each of these is a decision that changes the numbers, so they are stated rather than
buried:

- **Annual only.** Every figure is a DFP filing with a 12-month span. An ITR prints
  each account twice under one reference date — the discrete quarter and the
  year-to-date figure — and mixing them is the most common way to produce a
  confidently wrong series.
- **Consecutive years only.** A company that skipped a filing is excluded, rather
  than having two non-adjacent years compared and called growth.
- **R$100mm prior-year revenue floor.** Without it, a company going from R$1mm to
  R$3mm posts 200% growth and owns every leaderboard.
- **Net income is conta 3.11 only — no fallback.** `3.09` is profit *before*
  statutory profit-sharing (`3.10`); substituting it overstates net income by the
  participations line. A filer that did not report `3.11` shows null.
- **Newest version only.** A restatement refiles under a higher `versao` and the old
  rows remain, so only the newest is read and no year appears twice with two
  different numbers.
- **Consolidated scope** (`escopo = 'con'`) throughout. Individual-scope figures are
  a different company for any group with subsidiaries.
- **Sectors with fewer than five comparable companies get no median**, so those
  companies show a blank `vs sector` rather than a rank against two peers.

[Full financials explorer →](/financials) · [Company universe →](/) ·
[Corporate events →](/events)
