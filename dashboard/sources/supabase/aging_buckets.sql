-- Zero-row guard — see delinquency_trend.sql. An empty 12-month window here
-- would fail the entire build, so a single all-NULL row is emitted when the
-- aggregate is empty.
with agg as (
  select
    period,
    sum(vl_inad_30)         / 1e6 as inad_30d,
    sum(vl_inad_60)         / 1e6 as inad_60d,
    sum(vl_inad_90)         / 1e6 as inad_90d,
    sum(vl_inad_180)        / 1e6 as inad_180d,
    sum(vl_inad_360)        / 1e6 as inad_360d,
    sum(vl_inad_maior_1080) / 1e6 as inad_over1080d
  from cvm_fidc_aging
  where period >= current_date - interval '12 months'
    -- completeness clamp (mv_period_completeness)
    and period <= latest_complete_period('fidc')
  group by period
)
select period, inad_30d, inad_60d, inad_90d, inad_180d, inad_360d, inad_over1080d
from agg
union all
select null::date, null::numeric, null::numeric, null::numeric,
       null::numeric, null::numeric, null::numeric
where not exists (select 1 from agg)
order by period nulls last
