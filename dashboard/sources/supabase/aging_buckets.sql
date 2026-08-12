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
group by period
order by period
