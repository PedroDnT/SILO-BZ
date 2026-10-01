-- /rates: NTN-B (Tesouro IPCA+) held by investment funds, monthly, from CVM's
-- CDA portfolio filings (cvm_fi_cda, block 1 "Títulos Públicos").
--
-- WHAT IS COUNTED: rows with tp_titpub = 'NOTAS DO TESOURO NACIONAL SERIE B'
-- and tp_aplic = 'Títulos Públicos', valued at vl_merc_pos_final (market value
-- the fund reported). Repo collateral (tp_aplic = 'Operações Compromissadas')
-- is EXCLUDED: it is a loan backed by NTN-Bs, not a holding. The key of
-- cvm_fi_cda includes cd_isin, so each maturity a fund holds is its own row and
-- is summed, not collapsed. Funds of funds hold quotas, not bonds, so a bond is
-- counted once, by the fund that holds it.
--
-- SPINE END: the last month whose count of NTN-B-holding funds is at least 90%
-- of the median of the 12 months before it. The newest CDA months are partly
-- filed (2026-06 to 2026-08 held about 60% of the usual funds when this was
-- written) and drawing them reads as a sell-off. The page says where it stops.
--
-- WINDOW: 36 months, to keep the build query bounded on a large table.
--
-- ZERO-ROW SAFETY: a month spine drives the row count; the holdings are LEFT
-- JOINed on, so an empty table yields NULLs, never a 0-row source.
with monthly as (
  select
    period,
    count(distinct cnpj)     as n_funds,
    sum(vl_merc_pos_final)   as v
  from cvm_fi_cda
  where tp_titpub = 'NOTAS DO TESOURO NACIONAL SERIE B'
    and tp_aplic  = 'Títulos Públicos'
    and period   >= (date_trunc('month', current_date) - interval '48 months')::date
  group by period
),
anchor as (
  select coalesce(max(m.period), date_trunc('month', current_date)::date) as p_end
  from monthly m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from monthly p
    where p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
),
spine as (
  select generate_series(
           a.p_end - interval '35 months',
           a.p_end,
           interval '1 month'
         )::date as period
  from anchor a
)
select
  s.period,
  m.v / 1e9    as ntnb_bn,
  m.n_funds
from spine s
left join monthly m on m.period = s.period
order by s.period
