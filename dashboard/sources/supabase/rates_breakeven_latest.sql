-- /rates and the home page: nominal, real and breakeven at the standard
-- tenors (1y, 2y, 5y, 10y) on the latest session.
--
-- Each tenor is a B3 FIXED vertex (vertex_type F; nominal tenor 360, 720,
-- 1800 and 3600 calendar days in vertex_code), published on every session
-- since 2008-01-02 for both curves, so nothing is interpolated. Rates are
-- % a.a. on 252 business days; breakeven = (1 + PRE) / (1 + DPL) - 1.
-- The 10y vertex can sit in B3's extrapolated tail when no DAP contract
-- reaches it; the page says so.
--
-- ZERO-ROW SAFETY: the four-row tenor driver fixes the row count; the curves
-- are LEFT JOINed on, so an empty table yields NULLs, never a 0-row source.
with tenors (tenor_days, tenor_label, sort_key) as (
  values (360, '1y', 1), (720, '2y', 2), (1800, '5y', 3), (3600, '10y', 4)
),
last_session as (
  select max(trade_date) as d
  from b3_reference_rate
  where curve = 'PRE'
),
fixed as (
  select r.curve, r.vertex_code, r.business_days, r.rate
  from b3_reference_rate r
  join last_session s on r.trade_date = s.d
  where r.curve in ('PRE', 'DPL')
    and r.vertex_type = 'F'
    and r.vertex_code in ('00360', '00720', '01800', '03600')
)
select
  t.tenor_label,
  t.tenor_days,
  t.sort_key,
  (select d from last_session)                         as trade_date,
  max(f.business_days) filter (where f.curve = 'PRE')  as business_days,
  max(f.rate) filter (where f.curve = 'PRE')           as nominal_num2,
  max(f.rate) filter (where f.curve = 'DPL')           as real_num2,
  ((1 + max(f.rate) filter (where f.curve = 'PRE') / 100)
   / (1 + max(f.rate) filter (where f.curve = 'DPL') / 100) - 1) * 100
                                                       as breakeven_num2
from tenors t
left join fixed f
  on f.vertex_code = lpad(t.tenor_days::text, 5, '0')
group by t.tenor_label, t.tenor_days, t.sort_key
order by t.sort_key
