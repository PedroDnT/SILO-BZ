-- Coverage counter for the FII property explorer.
--
-- Reads cvm_fii_imovel (the property-register member of the INF_TRIMESTRAL zip).
-- If these read zero, the explorer below is empty because the register has not
-- been ingested for that period — not because Brazilian FIIs own no buildings.
-- CVM leaves the operational fields (vacancy, delinquency) blank for a large
-- minority of buildings, so the two "with" counters are the honest denominator
-- for anything computed from them.
--
-- ZERO-ROW SAFETY: aggregate with no GROUP BY -> exactly one row, always.
select
  count(*)                                                     as property_rows,
  count(distinct i.cnpj)                                       as funds_with_register,
  max(i.data_referencia)                                       as latest_reference,
  count(*) filter (where i.nome_imovel is not null)            as rows_with_property_name,
  count(*) filter (where i.pr_imovel_total_investido is not null)
                                                               as rows_with_invested_share,
  count(*) filter (where i.pr_vacancia is not null)            as rows_with_vacancy,
  count(*) filter (where i.pr_inadimplencia is not null)       as rows_with_delinquency,
  count(*) filter (where i.pr_imovel_total_investido > 50)     as rows_single_asset_over_50pct
from cvm_fii_imovel i
