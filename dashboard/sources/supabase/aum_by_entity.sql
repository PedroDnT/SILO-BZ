-- Net assets by fund family, last 12 months, for the home-page stacked area.
--
-- fact_fund_monthly keeps each family's RAW period convention (FI first-of-
-- month, FIDC month-end, FIP 31-Dec). Grouped on the raw date, a stacked chart
-- gets two x-points per month — one where only FI has a value and one where
-- only FIDC does — and draws a sawtooth that falls to zero between them. Every
-- other family chart on the site groups on date_trunc('month', period).
--
-- Two more rules a STACKED area needs, both measured on the live site
-- (2026-09-15):
--   * FIP is excluded. It files yearly and is keyed 31-Dec, so it lands in
--     exactly one month of twelve as a R$1.75tn band larger than FIDC + FII +
--     FIAGRO together — a mountain, not a series. Its figure is the tile
--     beside the chart (fip_latest.sql) and the yearly bars on /industry.
--   * The stack ends at the LAST MONTH EVERY MONTHLY FAMILY HAS FILED
--     (LEAST of the four completeness clamps), not at each family's own.
--     Clamped per family, only FI had the newest month and the total fell
--     from ~R$15.6tn to R$14.3tn at the right edge — a cliff that read as an
--     outflow.
--
-- PLAN SHAPE MATTERS HERE (measured on production, 2026-09-16). The first
-- version of this anchor was a plain CTE and the window predicate wrapped
-- f.period in date_trunc(). Postgres inlined the CTE and evaluated the four
-- latest_complete_period() calls INSIDE the row filter of an index-only scan
-- over all 2.35M fact rows — 37 minutes for one 48-row source, and every
-- dashboard build since #228 died at Vercel's 45-minute limit (the previous
-- shape took 48 s). Hence:
--   * `as materialized` — the anchor is computed once, as a CTE scan;
--   * the window is a RANGE ON THE RAW period column, so it is an Index Cond
--     on ix_fact_fund_monthly_period, not a per-row expression. The bounds
--     are month-aligned, and every family's raw period falls inside its own
--     calendar month, so the range selects the same 12 months as
--     date_trunc('month', period) BETWEEN p_end - 11 months AND p_end.
-- Same 48 rows, 0.6 s.
with anchor as materialized (
  select date_trunc('month', least(
           latest_complete_period('fi'),
           latest_complete_period('fidc'),
           latest_complete_period('fii'),
           latest_complete_period('fiagro')
         ))::date as p_end
)
select
  f.entity_type,
  date_trunc('month', f.period)::date as period,
  sum(f.vl_patrim_liq) / 1e9          as aum_bn
from fact_fund_monthly f
cross join anchor a
where f.entity_type <> 'fip'
  and f.period >= (a.p_end - interval '11 months')::date
  and f.period <  (a.p_end + interval '1 month')::date
group by f.entity_type, date_trunc('month', f.period)
order by period desc, aum_bn desc
