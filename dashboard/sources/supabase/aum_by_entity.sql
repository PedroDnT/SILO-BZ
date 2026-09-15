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
with anchor as (
  select least(
           latest_complete_period('fi'),
           latest_complete_period('fidc'),
           latest_complete_period('fii'),
           latest_complete_period('fiagro')
         ) as p_end
)
select
  f.entity_type,
  date_trunc('month', f.period)::date as period,
  sum(f.vl_patrim_liq) / 1e9          as aum_bn
from fact_fund_monthly f
cross join anchor a
where f.entity_type <> 'fip'
  and date_trunc('month', f.period)::date >  (date_trunc('month', a.p_end) - interval '12 months')::date
  and date_trunc('month', f.period)::date <= date_trunc('month', a.p_end)::date
group by f.entity_type, date_trunc('month', f.period)
order by period desc, aum_bn desc
