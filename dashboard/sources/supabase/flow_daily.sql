-- Fluxo de investidores — daily net flow by investor type, in R$ bn.
--
-- Derived, not published: B3 publishes a MONTH-TO-DATE cumulative snapshot with
-- a T+2 lag, and fact_investor_flow_daily takes first differences within each
-- month. Rows the derivation cannot honestly interpret (the first snapshot we
-- hold in a month, when that is not the month's first session) carry NULL and
-- flow_basis = 'unknown_opening_snapshot'; they are dropped here rather than
-- charted as a zero, because a zero would read as "nobody traded".
--
-- The cumulative line the page draws is a running sum over what we DO hold, so
-- it is an accumulation from the start of coverage — not a claim about the year.
select
  f.reference_date,
  f.investor_type,
  f.flow_basis,
  f.net_brl_mil / 1e6     as net_brl_bn,
  f.compras_brl_mil / 1e6 as compras_brl_bn,
  f.vendas_brl_mil / 1e6  as vendas_brl_bn,
  sum(f.net_brl_mil / 1e6) over (
    partition by f.investor_type order by f.reference_date
  )                       as net_acum_brl_bn
from fact_investor_flow_daily f
where f.net_brl_mil is not null
order by f.reference_date, f.investor_type
