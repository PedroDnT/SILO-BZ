-- How much of the fund registry actually carries an administrator / gestor name.
--
-- This is the honesty check for the whole /managers page. admin_name and
-- gestor_name were added to cvm_fund_registry by migration 11 and are lifted
-- from CVM's cadastral CSVs at ingest; nothing derives or guesses them, so a
-- fund whose cadastral row was never ingested simply has no name and is absent
-- from every league table on the page. These counts say by how much.
--
-- Aggregates with no GROUP BY, so exactly one row always comes back — the shape
-- Evidence needs (a 0-row source writes a zero-byte parquet and breaks the
-- build).
--
-- ranking_period excludes FIP deliberately: FIP is stored at 31-DEC of its
-- reporting year, so plain max(period) is a future, FIP-only date. This is the
-- same period the league tables are pinned to.
select
  count(*)                                                                        as registry_rows,
  count(*) filter (where admin_name is not null)                                  as rows_with_admin,
  count(*) filter (where gestor_name is not null)                                 as rows_with_gestor,
  round(100.0 * count(*) filter (where admin_name is not null)
        / nullif(count(*), 0), 1)                                                 as admin_coverage_pct,
  round(100.0 * count(*) filter (where gestor_name is not null)
        / nullif(count(*), 0), 1)                                                 as gestor_coverage_pct,
  count(distinct admin_name)                                                      as n_administrators,
  count(distinct gestor_name)                                                     as n_gestores,
  (select count(*) from dim_fund)                                                 as funds_in_universe,
  (select max(period) from fact_fund_monthly where entity_type <> 'fip')          as ranking_period
from cvm_fund_registry
