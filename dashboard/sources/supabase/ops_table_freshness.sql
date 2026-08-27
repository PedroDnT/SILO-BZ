-- Latest reference date actually present in each core ingest table.
--
-- The ingest log records what the pipeline THINKS it did; this reads the tables
-- themselves. The two disagreeing — a recent 'ok' run over a table whose newest
-- row is months old — is the failure mode worth catching.
--
-- Each branch returns exactly one row even when that table is empty, so the
-- UNION ALL is a fixed 10 rows. A 0-row source writes a zero-byte parquet and
-- breaks the Evidence build.
--
-- Each table is dated on its own natural key column, named in date_column so the
-- grains are never silently mixed: cvm_fip_periodic is YEARLY (period_year,
-- mapped to 31-Dec here purely so the column is comparable) and the securit
-- tables are yearly files as well.
--
-- Sorted worst-first through coalesce so an EMPTY table (NULL latest) sorts
-- above a merely stale one instead of drifting to the bottom.
--
-- PERFORMANCE / n_rows_est: this source used to run count(*) over all ten
-- tables and cost 5m04s of a 31-minute Vercel build to emit ten rows — the
-- single biggest contributor to the BUILD_EXCEEDED_MAXIMUM_TIME failures on
-- 2026-08-26. The max(date) half is an index-only lookup and stays exact; the
-- count half is now pg_class.reltuples, refreshed by the ANALYZE the daily
-- ingest runs after every upsert and accurate to ~1%. The column is renamed
-- n_rows_est (and the page labels it "≈") because presenting a planner
-- estimate as an exact count would be a lie about the data, which this repo
-- does not do. reltuples is -1 on a never-analyzed table in PG14+, floored to
-- 0 here — a 0 means "not yet analyzed" and is worth seeing on an ops page.
with est as (
    select c.relname, greatest(c.reltuples, 0)::bigint as n_rows_est
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
)
select *
from (
select 'cvm_fi_diario'     as table_name, 'dt_comptc'   as date_column, (select n_rows_est from est where relname = 'cvm_fi_diario')     as n_rows_est, max(dt_comptc) as latest, (current_date - max(dt_comptc)) as days_stale from cvm_fi_diario
union all
select 'cvm_fi_balancete',  'dt_comptc', (select n_rows_est from est where relname = 'cvm_fi_balancete'),  max(dt_comptc), (current_date - max(dt_comptc)) from cvm_fi_balancete
union all
select 'cvm_fidc_mensal',   'period',    (select n_rows_est from est where relname = 'cvm_fidc_mensal'),   max(period),    (current_date - max(period))    from cvm_fidc_mensal
union all
select 'cvm_fidc_tranche',  'period',    (select n_rows_est from est where relname = 'cvm_fidc_tranche'),  max(period),    (current_date - max(period))    from cvm_fidc_tranche
union all
select 'cvm_fidc_aging',    'period',    (select n_rows_est from est where relname = 'cvm_fidc_aging'),    max(period),    (current_date - max(period))    from cvm_fidc_aging
union all
select 'cvm_fiagro_mensal', 'period',    (select n_rows_est from est where relname = 'cvm_fiagro_mensal'), max(period),    (current_date - max(period))    from cvm_fiagro_mensal
union all
select 'cvm_fii_mensal',    'period',    (select n_rows_est from est where relname = 'cvm_fii_mensal'),    max(period),    (current_date - max(period))    from cvm_fii_mensal
union all
select 'cvm_fip_periodic',  'period_year (yearly)', (select n_rows_est from est where relname = 'cvm_fip_periodic'), make_date(max(period_year), 12, 31), (current_date - make_date(max(period_year), 12, 31)) from cvm_fip_periodic
union all
select 'bacen_sgs',         'reference_date', (select n_rows_est from est where relname = 'bacen_sgs'),  max(reference_date), (current_date - max(reference_date)) from bacen_sgs
union all
select 'bacen_ptax',        'reference_date', (select n_rows_est from est where relname = 'bacen_ptax'), max(reference_date), (current_date - max(reference_date)) from bacen_ptax
) t
order by coalesce(days_stale, 99999) desc
