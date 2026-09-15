-- Net assets by fund family, last 12 months, for the home-page stacked area.
--
-- fact_fund_monthly keeps each family's RAW period convention (FI first-of-
-- month, FIDC month-end, FIP 31-Dec). Grouped on the raw date, a stacked chart
-- gets two x-points per month — one where only FI has a value and one where
-- only FIDC does — and draws a sawtooth that falls to zero between them. Every
-- other family chart on the site groups on date_trunc('month', period); this
-- one did not.
select
  entity_type,
  date_trunc('month', period)::date as period,
  sum(vl_patrim_liq) / 1e9 as aum_bn
from fact_fund_monthly
where period >= current_date - interval '12 months'
  -- per-family completeness clamp (mv_period_completeness)
  and period <= latest_complete_period(entity_type)
group by entity_type, date_trunc('month', period)
order by period desc, aum_bn desc
