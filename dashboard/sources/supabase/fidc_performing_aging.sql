-- PERFORMING receivables by remaining-term bucket, monthly.
--
-- These are the vl_prazo_* columns of cvm_fidc_aging — the "A" bands of CVM
-- tab_VI, credits that are NOT yet overdue, bucketed by days to maturity. They
-- have been ingested since the FIDC aging dataset was wired
-- (src/parsers/field_maps/fidc_aging.py maps all ten) but nothing in the
-- dashboard has ever read them: the existing aging chart shows only the "B"
-- (vl_inad_*) delinquent bands.
--
-- This is the asset-side maturity profile, and it is what a delinquency rate
-- cannot tell you: a book whose performing balance is concentrated in the
-- 720d+ buckets is carrying long-duration risk that has simply not come due
-- yet, so today's low delinquency says little about next year's.
--
-- ZERO-ROW SAFETY: generate_series over the last 12 months drives the rows; the
-- aggregate is LEFT JOINed, so an unpublished month is NULL rather than absent.
with months as (
  select generate_series(
           date_trunc('month', current_date - interval '11 months'),
           date_trunc('month', current_date),
           interval '1 month'
         )::date as period
),
agg as (
  select
    date_trunc('month', a.period)::date      as period,
    sum(a.vl_prazo_30)         / 1e6         as perf_30d,
    sum(a.vl_prazo_60)         / 1e6         as perf_60d,
    sum(a.vl_prazo_90)         / 1e6         as perf_90d,
    sum(a.vl_prazo_120)        / 1e6         as perf_120d,
    sum(a.vl_prazo_150)        / 1e6         as perf_150d,
    sum(a.vl_prazo_180)        / 1e6         as perf_180d,
    sum(a.vl_prazo_360)        / 1e6         as perf_360d,
    sum(a.vl_prazo_720)        / 1e6         as perf_720d,
    sum(a.vl_prazo_1080)       / 1e6         as perf_1080d,
    sum(a.vl_prazo_maior_1080) / 1e6         as perf_over1080d,
    sum(a.vl_total_inad)       / 1e6         as inad_total_mm,
    count(distinct a.cnpj)                   as n_funds
  from cvm_fidc_aging a
  where a.period >= (date_trunc('month', current_date) - interval '11 months')::date
  group by date_trunc('month', a.period)::date
)
select
  m.period,
  a.perf_30d,
  a.perf_60d,
  a.perf_90d,
  a.perf_120d,
  a.perf_150d,
  a.perf_180d,
  a.perf_360d,
  a.perf_720d,
  a.perf_1080d,
  a.perf_over1080d,
  a.inad_total_mm,
  a.n_funds
from months m
left join agg a on a.period = m.period
order by m.period
