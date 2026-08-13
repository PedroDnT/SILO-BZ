-- Per-fund profile cards for the 12 largest funds, via fund_profile(cnpj).
--
-- fund_profile() takes a CNPJ, so it is driven from a SMALL, bounded set (the 12
-- largest funds from search_funds) rather than every fund — one RPC call per row
-- keeps both the query and the parquet small.
--
-- peak_aum vs latest_aum is the interesting pair: a fund far below its peak has
-- either paid out or been redeemed, and is_active flags whether it has reported
-- in the last 90 days at all.
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL.
select
  x.fund_name         as fund_name,
  x.cnpj              as cnpj,
  x.entity_type       as entity_type,
  x.status            as status,
  x.is_active         as is_active,
  x.first_period      as first_period,
  x.last_period       as last_period,
  x.months_reported   as months_reported,
  x.peak_aum_mm       as peak_aum_mm,
  x.latest_aum_mm     as latest_aum_mm,
  x.pct_of_peak       as pct_of_peak
from (values (1)) as g(one)
left join lateral (
  select
    coalesce(p.fund_name, p.cnpj)                                     as fund_name,
    p.cnpj                                                            as cnpj,
    p.entity_type                                                     as entity_type,
    p.status                                                          as status,
    p.is_active                                                       as is_active,
    p.first_period                                                    as first_period,
    p.last_period                                                     as last_period,
    p.n_months_reported                                               as months_reported,
    p.peak_aum / 1e6                                                  as peak_aum_mm,
    p.latest_aum / 1e6                                                as latest_aum_mm,
    round(100.0 * p.latest_aum / nullif(p.peak_aum, 0), 1)            as pct_of_peak
  from search_funds('', null, 12) s
  cross join lateral fund_profile(s.cnpj) p
) x on true
order by x.latest_aum_mm desc nulls last
