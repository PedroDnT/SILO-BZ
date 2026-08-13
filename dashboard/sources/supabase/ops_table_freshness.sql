-- Latest reference date actually present in each core ingest table.
--
-- The ingest log records what the pipeline THINKS it did; this reads the tables
-- themselves. The two disagreeing — a recent 'ok' run over a table whose newest
-- row is months old — is the failure mode worth catching.
--
-- Each branch is an aggregate over one table and therefore returns exactly one
-- row even when that table is empty, so the UNION ALL is a fixed 10 rows. A
-- 0-row source writes a zero-byte parquet and breaks the Evidence build.
--
-- Each table is dated on its own natural key column, named in date_column so the
-- grains are never silently mixed: cvm_fip_periodic is YEARLY (period_year,
-- mapped to 31-Dec here purely so the column is comparable) and the securit
-- tables are yearly files as well.
--
-- Sorted worst-first through coalesce so an EMPTY table (NULL latest) sorts
-- above a merely stale one instead of drifting to the bottom.
select *
from (
select 'cvm_fi_diario'     as table_name, 'dt_comptc'   as date_column, count(*) as n_rows, max(dt_comptc) as latest, (current_date - max(dt_comptc)) as days_stale from cvm_fi_diario
union all
select 'cvm_fi_balancete',  'dt_comptc', count(*), max(dt_comptc), (current_date - max(dt_comptc)) from cvm_fi_balancete
union all
select 'cvm_fidc_mensal',   'period',    count(*), max(period),    (current_date - max(period))    from cvm_fidc_mensal
union all
select 'cvm_fidc_tranche',  'period',    count(*), max(period),    (current_date - max(period))    from cvm_fidc_tranche
union all
select 'cvm_fidc_aging',    'period',    count(*), max(period),    (current_date - max(period))    from cvm_fidc_aging
union all
select 'cvm_fiagro_mensal', 'period',    count(*), max(period),    (current_date - max(period))    from cvm_fiagro_mensal
union all
select 'cvm_fii_mensal',    'period',    count(*), max(period),    (current_date - max(period))    from cvm_fii_mensal
union all
select 'cvm_fip_periodic',  'period_year (yearly)', count(*), make_date(max(period_year), 12, 31), (current_date - make_date(max(period_year), 12, 31)) from cvm_fip_periodic
union all
select 'bacen_sgs',         'reference_date', count(*), max(reference_date), (current_date - max(reference_date)) from bacen_sgs
union all
select 'bacen_ptax',        'reference_date', count(*), max(reference_date), (current_date - max(reference_date)) from bacen_ptax
) t
order by coalesce(days_stale, 99999) desc
