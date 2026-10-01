-- /etf: total ETF net assets as ANBIMA's monthly bulletin reports them
-- (anbima_etf_class_monthly, level 'category', metric pl_brl_mm, R$ million).
--
-- The history is as sparse as the source: one point per year-end for
-- 2006-12 to 2024-12, then monthly from 2025-01. Only the points ANBIMA
-- published are returned; nothing is interpolated between year-ends.
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the points, so an empty table
-- yields one NULL row, never a 0-row source.
with pts as (
  select
    reference_date,
    value / 1000 as pl_bn
  from anbima_etf_class_monthly
  where level = 'category'
    and anbima_type_name = 'ETF'
    and metric = 'pl_brl_mm'
)
select p.reference_date, p.pl_bn
from (select 1) as one
left join pts p on true
order by p.reference_date
