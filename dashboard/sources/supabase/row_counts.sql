-- Headline row inventory for the four landing tables the Overview cites.
--
-- ESTIMATES, NOT EXACT COUNTS. count(*) on these tables is a full sequential
-- scan — cvm_fi_diario alone is tens of millions of rows — and this source
-- cost 2m19s of a 31-minute Vercel build to produce four numbers. The daily
-- ingest workflow runs ANALYZE on every one of these tables immediately after
-- upsert, so pg_class.reltuples is refreshed once a day and lands within ~1%
-- of the true count. That is far inside the precision an order-of-magnitude
-- inventory tile needs.
--
-- The column is named rows_est and the page labels it "≈" so nobody reads an
-- estimate as a census: this is a planner statistic, and the honest thing is
-- to say so rather than to present it as an exact figure.
--
-- reltuples is -1 on a table that has never been analyzed (PG 14+), and the
-- greatest(...) below floors that to 0 rather than showing a negative count.
-- A zero here means "not yet analyzed", which is itself worth seeing on an
-- ops surface.
select
    'FI diário'     as dataset,
    greatest(c.reltuples, 0)::bigint as rows_est
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'cvm_fi_diario'
union all
select 'FIDC mensal', greatest(c.reltuples, 0)::bigint
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'cvm_fidc_mensal'
union all
select 'FII mensal', greatest(c.reltuples, 0)::bigint
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'cvm_fii_mensal'
union all
select 'SECURIT série', greatest(c.reltuples, 0)::bigint
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname = 'cvm_securit_serie'
