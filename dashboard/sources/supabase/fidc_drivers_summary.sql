-- Headline counts for the FIDC delinquency-drivers block on /fidc.
-- One definition: fidc_delinquency_drivers() in 15_fraud_screens.sql, called
-- with its defaults (12 complete months ending latest_complete_period('fidc'),
-- >= 6 observations, value threshold R$1mm, rate threshold 1 p.p.). "Active"
-- = latest net assets >= R$10mm, the report's floor. An aggregate with no
-- GROUP BY always returns one row, so no zero-row guard is needed.
with d as (
  select * from fidc_delinquency_drivers()
)
select
  min(window_from)                                                              as window_from,
  max(window_to)                                                                as window_to,
  count(*)                                                                      as n_funds,
  count(*) filter (where nav_end >= 1e7)                                        as n_active,
  count(*) filter (where nav_end >= 1e7 and driver = 'consistent_worsening')    as n_consistent,
  count(*) filter (where nav_end >= 1e7 and driver = 'value_up_rate_masked')    as n_masked,
  count(*) filter (where nav_end >= 1e7 and driver = 'denominator_only')        as n_denominator,
  count(*) filter (where nav_end >= 1e7 and driver = 'improvement')             as n_improvement,
  count(*) filter (where nav_end >= 1e7 and driver = 'stable')                  as n_stable,
  count(*) filter (where stopped_reporting)                                     as n_stopped,
  sum(delta_brl) filter (where nav_end >= 1e7 and driver = 'consistent_worsening') / 1e9 as consistent_delta_bn,
  sum(delta_brl) filter (where nav_end >= 1e7 and driver = 'value_up_rate_masked') / 1e9 as masked_delta_bn
from d
