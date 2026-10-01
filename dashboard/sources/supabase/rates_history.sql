-- /rates: 1y and 5y nominal, real and breakeven since 2008, WEEKLY (the last
-- session of each week), from B3's fixed vertices 360 and 1800 calendar days.
--
-- Weekly, not daily, to keep the parquet small; the last session in the week
-- is a published fix, not an average. Same method as rates_breakeven_latest:
-- PRE and DPL are % a.a. on 252 business days, breakeven = (1 + PRE) /
-- (1 + DPL) - 1 at the same vertex, nothing interpolated.
--
-- FOCUS: focus_ipca_12m_num2 is the BACEN Focus survey's median for IPCA over
-- the next 12 months (bacen_expectativas, ExpectativasMercadoInflacao12Meses;
-- the fetch keeps the unsmoothed series, Suavizada='N'), read on the same date
-- as the curve session and left blank when Focus has no row that day. It
-- starts 2019-01. A survey median and a market breakeven are different things:
-- the breakeven also carries an inflation risk premium.
--
-- ZERO-ROW SAFETY: a generate_series week spine from 2008-01-07 to the current
-- week drives the row count; the curves are LEFT JOINed on, so an empty table
-- yields NULLs, never a 0-row source. The current week is included: its last
-- session so far is a published fix like any other.
with spine as (
  select generate_series(
           date '2008-01-07',
           date_trunc('week', current_date)::date,
           interval '1 week'
         )::date as week
),
fixed as (
  select
    date_trunc('week', r.trade_date)::date as week,
    r.trade_date,
    r.curve,
    r.vertex_code,
    r.rate
  from b3_reference_rate r
  where r.curve in ('PRE', 'DPL')
    and r.vertex_type = 'F'
    and r.vertex_code in ('00360', '01800')
),
last_in_week as (
  select week, max(trade_date) as trade_date
  from fixed
  group by week
),
wide as (
  select
    l.week,
    l.trade_date,
    max(f.rate) filter (where f.curve = 'PRE' and f.vertex_code = '00360') as pre_1y,
    max(f.rate) filter (where f.curve = 'DPL' and f.vertex_code = '00360') as dpl_1y,
    max(f.rate) filter (where f.curve = 'PRE' and f.vertex_code = '01800') as pre_5y,
    max(f.rate) filter (where f.curve = 'DPL' and f.vertex_code = '01800') as dpl_5y
  from last_in_week l
  join fixed f on f.trade_date = l.trade_date
  group by l.week, l.trade_date
)
select
  s.week,
  w.trade_date,
  w.pre_1y                                            as nominal_1y_num2,
  w.dpl_1y                                            as real_1y_num2,
  ((1 + w.pre_1y / 100) / (1 + w.dpl_1y / 100) - 1) * 100 as breakeven_1y_num2,
  w.pre_5y                                            as nominal_5y_num2,
  w.dpl_5y                                            as real_5y_num2,
  ((1 + w.pre_5y / 100) / (1 + w.dpl_5y / 100) - 1) * 100 as breakeven_5y_num2,
  fx.median                                           as focus_ipca_12m_num2
from spine s
left join wide w on w.week = s.week
left join bacen_expectativas fx
  on fx.reference_date = w.trade_date
 and fx.endpoint_name  = 'ExpectativasMercadoInflacao12Meses'
 and fx.indicador      = 'IPCA'
order by s.week
