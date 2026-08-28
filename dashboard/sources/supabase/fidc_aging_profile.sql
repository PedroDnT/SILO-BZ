-- Performing vs delinquent receivables side by side, bucket by bucket, at the
-- latest reported period.
--
-- The ten buckets of CVM tab_VI exist twice in cvm_fidc_aging: vl_prazo_* (band
-- A, days remaining to maturity — still performing) and vl_inad_* (band B, days
-- already overdue). Putting them on one axis is the only view that shows both
-- halves of the same book.
--
-- ZERO-ROW SAFETY, and this one is structural rather than defensive: `totals`
-- is a bare aggregate with no GROUP BY, so it returns exactly one row even over
-- an empty cvm_fidc_aging; unnesting it against the ten fixed bucket labels
-- therefore always produces exactly ten rows. An empty table yields ten rows of
-- NULL measures — the bucket axis is a property of the CVM form, not of the
-- data, so it is right for it to be present regardless.
--
-- Bucket labels are zero-prefixed ("01 …" … "10 …") so that any downstream
-- alphabetical sort still lands in chronological order.
with latest as (
  -- Completeness clamp, matching every other /fidc source: bare max(period)
  -- lands on a partially-filed trailing month, so the "latest period" profile
  -- was summing only the funds that had already reported and reading as a
  -- collapse in receivables. latest_complete_period keeps FIDC's month-end
  -- convention, so this compares like with like.
  select max(period) as period
    from cvm_fidc_aging
   where period <= latest_complete_period('fidc')
),
totals as (
  select
    sum(a.vl_prazo_30)          as p30,
    sum(a.vl_prazo_60)          as p60,
    sum(a.vl_prazo_90)          as p90,
    sum(a.vl_prazo_120)         as p120,
    sum(a.vl_prazo_150)         as p150,
    sum(a.vl_prazo_180)         as p180,
    sum(a.vl_prazo_360)         as p360,
    sum(a.vl_prazo_720)         as p720,
    sum(a.vl_prazo_1080)        as p1080,
    sum(a.vl_prazo_maior_1080)  as pmais,
    sum(a.vl_inad_30)           as i30,
    sum(a.vl_inad_60)           as i60,
    sum(a.vl_inad_90)           as i90,
    sum(a.vl_inad_120)          as i120,
    sum(a.vl_inad_150)          as i150,
    sum(a.vl_inad_180)          as i180,
    sum(a.vl_inad_360)          as i360,
    sum(a.vl_inad_720)          as i720,
    sum(a.vl_inad_1080)         as i1080,
    sum(a.vl_inad_maior_1080)   as imais,
    count(distinct a.cnpj)      as n_funds,
    max(a.period)               as period
  from cvm_fidc_aging a
  join latest l on a.period = l.period
),
buckets as (
  select
    t.period,
    t.n_funds,
    v.bucket,
    v.performing,
    v.delinquent
  from totals t
  cross join lateral unnest(
    array[
      '01 ate 30d', '02 31-60d', '03 61-90d', '04 91-120d', '05 121-150d',
      '06 151-180d', '07 181-360d', '08 361-720d', '09 721-1080d', '10 >1080d'
    ],
    array[t.p30, t.p60, t.p90, t.p120, t.p150, t.p180, t.p360, t.p720, t.p1080, t.pmais],
    array[t.i30, t.i60, t.i90, t.i120, t.i150, t.i180, t.i360, t.i720, t.i1080, t.imais]
  ) as v(bucket, performing, delinquent)
)
select
  bucket,
  period,
  n_funds,
  performing / 1e6 as performing_mm,
  delinquent / 1e6 as delinquent_mm,
  round(
    100.0 * delinquent
    / nullif(coalesce(performing, 0) + coalesce(delinquent, 0), 0), 1
  ) as delinquent_num1
from buckets
order by bucket
