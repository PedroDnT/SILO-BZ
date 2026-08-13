-- The administrator universe by mandate count, from the dim_administrator view.
--
-- dim_administrator (src/store/analytical/13_dim_classification.sql) groups
-- cvm_fund_registry by admin_name and attaches each fund's MOST RECENT
-- fact_fund_monthly observation — so total_aum here is a latest-available AUM
-- per fund, not a single common period. That makes it a different (and staler)
-- number from the ranking table above, which pins every administrator to one
-- period; the two are not meant to tie out.
--
-- The view has one row per administrator that has a name, so it is empty when
-- registry name coverage is empty. A generate_series(1, 20) slot spine drives
-- the rows and the view is LEFT JOINed on, keeping the source at exactly 20 rows
-- — a 0-row source writes a zero-byte parquet and breaks the build.
--
-- n_active_funds counts cvm_fund_registry.is_active (migration 07), which is
-- derived from CVM's own status field; a fund with no status is not counted.
with ranked as (
  select
    row_number() over (order by n_funds desc, admin_name) as slot,
    admin_name,
    admin_cnpj,
    n_funds,
    n_active_funds,
    total_aum
  from dim_administrator
),
slots as (
  select generate_series(1, 20) as slot
)
select
  s.slot,
  r.admin_name,
  r.admin_cnpj,
  r.n_funds,
  r.n_active_funds,
  r.total_aum / 1e9 as aum_bn
from slots s
left join ranked r on r.slot = s.slot
order by s.slot
