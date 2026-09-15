-- /fidc delinquency-drivers block. Definition: fidc_delinquency_drivers()
-- (15_fraud_screens.sql); this source only filters, scales and orders.
-- Rates are percentage points (1.5 = 1.5%): never suffix them _pct.
-- Zero-row guard: an empty source is a 0-byte parquet that kills the whole
-- build; the union-all fallback emits one all-NULL row instead.
with d as (
  select
    cnpj,
    fund_name,
    driver,
    n_months,
    months_missing,
    first_month,
    last_month,
    delta_brl / 1e6      as delta_mm,
    del_start / 1e6      as del_start_mm,
    del_end / 1e6        as del_end_mm,
    nav_start / 1e6      as nav_start_mm,
    nav_end / 1e6        as nav_end_mm,
    delta_nav / 1e6      as delta_nav_mm,
    rate_start           as rate_start_num1,
    rate_end             as rate_end_num1,
    delta_pp             as delta_pp_num1,
    stopped_reporting
  from fidc_delinquency_drivers()
  where nav_end >= 1e7 and driver = 'denominator_only'
  order by delta_pp desc
  limit 15
)
select * from d
union all
select null::text, null::text, null::text, null::bigint, null::int, null::date, null::date,
       null::numeric, null::numeric, null::numeric, null::numeric, null::numeric, null::numeric,
       null::numeric, null::numeric, null::numeric, null::boolean
where not exists (select 1 from d)
