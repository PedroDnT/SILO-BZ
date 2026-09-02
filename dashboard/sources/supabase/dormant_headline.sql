-- /dormant headline tiles: the dormant-funds screen at FI's latest complete month.
--
-- ZERO-ROW SAFETY: a no-GROUP-BY aggregate over the screen's rows, so this is
-- always exactly one row. When the screen returns nothing the counts read 0 —
-- the truthful answer, not a 0-byte parquet.
--
-- The window is recomputed here from latest_complete_period('fi') rather than
-- read off the screen rows: with zero hits there would be no row to read it
-- from, and the tile must still say which months were examined. The lookback
-- literal (3) appears once, in `params`, and must match the page's stated
-- threshold and the other dormant_* sources.
--
-- to_char, not the raw date: a NULL date renders as the Unix epoch in Evidence
-- (see industry_class_latest.sql).
with params as (
  select 3 as lookback
),
bounds as (
  select
    latest_complete_period('fi')                                                 as win_to,
    (latest_complete_period('fi') - (p.lookback - 1) * interval '1 month')::date as win_from
  from params p
),
screen as (
  select s.*
  from params p
  cross join lateral fraud_screen_dormant_funds(p.lookback) s
),
universe as (
  -- every FI class with a row at the window's last month: the denominator
  select count(*) as funds_filing
  from fact_fund_monthly f
  cross join bounds b
  where f.entity_type = 'fi'
    and f.period = b.win_to
),
companies as (
  -- for scale only. coalesce, not a bare <>: NULL <> 'CANCELADA' is NULL and
  -- would silently drop a company with no recorded situação.
  select count(*) as listed_companies
  from cia_company
  where coalesce(situacao, '') <> 'CANCELADA'
)
select
  to_char(b.win_from, 'YYYY-MM-DD')                                            as window_from,
  to_char(b.win_to,   'YYYY-MM-DD')                                            as window_to,
  u.funds_filing,
  count(s.cnpj) filter (where s.dormancy = 'empty_shell')                      as empty_shells,
  count(s.cnpj) filter (where s.dormancy = 'parked_capital')                   as parked_capital,
  coalesce(sum(s.last_pl) filter (where s.dormancy = 'parked_capital'), 0) / 1e9 as parked_pl_bn,
  round(
    100.0 * count(s.cnpj) filter (where s.dormancy = 'parked_capital')
      / nullif(u.funds_filing, 0),
    1)                                                                         as parked_share_num1,
  c.listed_companies
from bounds b
cross join universe u
cross join companies c
left join screen s on true
group by b.win_from, b.win_to, u.funds_filing, c.listed_companies
