-- /rates: NTN-B held by funds on the latest complete CDA month, by maturity
-- year and by holding fund. Same rows and same spine end as
-- rates_ntnb_fund_holdings.sql (see there for what is counted and why the
-- newest months are skipped).
--
-- One source, two grains, told apart by `grain`:
--   'maturity'  one row per maturity year of dt_venc (the bond's own maturity
--               as the fund filed it)
--   'fund'      the 15 funds with the largest NTN-B position, named from
--               dim_fund, else the CNPJ
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the result, so an empty table
-- yields one NULL row, never a 0-row source.
with monthly as (
  select period, count(distinct cnpj) as n_funds
  from cvm_fi_cda
  where tp_titpub = 'NOTAS DO TESOURO NACIONAL SERIE B'
    and tp_aplic  = 'Títulos Públicos'
    and period   >= (date_trunc('month', current_date) - interval '24 months')::date
  group by period
),
anchor as (
  select max(m.period) as p_end
  from monthly m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from monthly p
    where p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
),
holdings as (
  select c.cnpj, c.dt_venc, c.vl_merc_pos_final as v, c.period
  from cvm_fi_cda c
  join anchor a on c.period = a.p_end
  where c.tp_titpub = 'NOTAS DO TESOURO NACIONAL SERIE B'
    and c.tp_aplic  = 'Títulos Públicos'
),
by_maturity as (
  select
    'maturity'::text                         as grain,
    extract(year from dt_venc)::int          as maturity_year,
    null::text                               as fund,
    sum(v) / 1e9                             as ntnb_bn,
    max(period)                              as period
  from holdings
  group by extract(year from dt_venc)
),
by_fund as (
  select
    'fund'::text                             as grain,
    null::int                                as maturity_year,
    coalesce(max(n.fund_name), h.cnpj)       as fund,
    sum(h.v) / 1e9                           as ntnb_bn,
    max(h.period)                            as period
  from holdings h
  -- one name per CNPJ: dim_fund can carry a CNPJ under more than one
  -- entity type, and joining it directly would double the position
  left join (
    select cnpj, max(fund_name) as fund_name from dim_fund group by cnpj
  ) n on n.cnpj = h.cnpj
  group by h.cnpj
  order by sum(h.v) desc
  limit 15
),
result as (
  select * from by_maturity
  union all
  select * from by_fund
)
select r.*
from (select 1) as one
left join result r on true
order by r.grain, r.maturity_year, r.ntnb_bn desc
