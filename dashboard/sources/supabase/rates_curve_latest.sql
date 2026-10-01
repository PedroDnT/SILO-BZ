-- /rates: the latest session's nominal (PRE) and real (DPL) B3 reference curves
-- on B3's FIXED vertices, plus the breakeven at each vertex from 1 year out.
--
-- Source: b3_reference_rate (TaxaSwap.txt), grain (curve, trade_date,
-- calendar_days). PRE = DI x pré, DPL = clean IPCA coupon (the real curve
-- NTN-Bs trade against). Both are % a.a. compounded on 252 business days
-- (api.curve_registry), so (1 + PRE) / (1 + DPL) - 1 at the same vertex is the
-- implied inflation B3 itself describes. Nothing is interpolated: only fixed
-- vertices (vertex_type F, nominal tenor in vertex_code) are read, and both
-- curves publish the same fixed tenors every session.
--
-- Breakeven is left NULL below 360 calendar days on purpose: DPL's short
-- vertices lean on the current month's IPCA projection, so a short breakeven
-- is a carry artefact, not an inflation expectation. Past the last DI1 / DAP
-- maturity B3 extrapolates (Manual de Curvas v21); the page says so.
--
-- ZERO-ROW SAFETY: a literal driver of B3's fixed nominal tenors (calendar
-- days, as published 2026-09-29) drives the row count; the curves are LEFT
-- JOINed on, so an empty table yields NULLs, never a 0-row source.
with tenors (tenor_days) as (
  values (30), (60), (90), (120), (150), (180), (210), (240), (270), (300),
         (330), (360), (390), (420), (450), (480), (510), (540), (570), (600),
         (630), (660), (690), (720), (750), (780), (810), (840), (870), (900),
         (930), (960), (990), (1020), (1050), (1080), (1110), (1140), (1170),
         (1200), (1440), (1800), (2160), (2520), (2880), (3240), (3600),
         (3960), (4320), (4680), (5040), (5400), (5580), (7200), (9000), (10800)
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
)
select
  t.tenor_days,
  round(t.tenor_days / 360.0, 2)                       as tenor_years,
  (select d from last_session)                         as trade_date,
  max(f.business_days) filter (where f.curve = 'PRE')  as business_days,
  max(f.rate) filter (where f.curve = 'PRE')           as nominal_num2,
  max(f.rate) filter (where f.curve = 'DPL')           as real_num2,
  case when t.tenor_days >= 360 then
    ((1 + max(f.rate) filter (where f.curve = 'PRE') / 100)
     / (1 + max(f.rate) filter (where f.curve = 'DPL') / 100) - 1) * 100
  end                                                  as breakeven_num2
from tenors t
left join fixed f
  on f.vertex_code = lpad(t.tenor_days::text, 5, '0')
group by t.tenor_days
order by t.tenor_days
