-- The gestor universe by mandate count, from the dim_gestor view.
--
-- dim_gestor (src/store/analytical/13_dim_classification.sql) is the gestor twin
-- of dim_administrator: grouped on cvm_fund_registry.gestor_name, with each
-- fund's most recent fact_fund_monthly observation summed into total_aum. Same
-- caveat — that AUM is latest-available per fund, not one shared period.
--
-- gestor_id is a CPF when the gestor is a natural person and a CNPJ when it is a
-- firm; it is carried straight from the cadastral file for drill-through and is
-- not reformatted here.
--
-- Slot spine (1..20) drives the rows so the source is always 20 rows even when
-- the view is empty; a 0-row source writes a zero-byte parquet and kills the
-- Evidence build. Blank slots mean the registry has no name there.
with ranked as (
  select
    row_number() over (order by n_funds desc, gestor_name) as slot,
    gestor_name,
    gestor_id,
    n_funds,
    n_active_funds,
    total_aum
  from dim_gestor
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.gestor_name,
  r.gestor_id,
  r.n_funds,
  r.n_active_funds,
  r.total_aum / 1e9 as aum_bn
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
