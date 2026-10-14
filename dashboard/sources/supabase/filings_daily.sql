-- /filings: documents SILO's FNET register holds per delivery day, last 90
-- complete days. Reads fnet_document directly (migration 42).
--
-- delivered_at is FNET's dataEntrega as printed, São Paulo local time, with no
-- zone: no AT TIME ZONE here. Today is excluded because the build runs in the
-- morning and today's deliveries are still arriving.
--
-- This is the REGISTER, not all of FNET: the daily per-type crawl covers FII,
-- FIDC and ETF documents, and history before SILO's first crawl is partial.
--
-- Zero-row safety: a generate_series spine LEFT JOINed to the counts, so this
-- is always 90 rows; a day with nothing delivered reads 0. The window is a
-- range on the raw delivered_at column (idx_fnet_document_delivered).
with spine as (
  select d::date as day
  from generate_series(current_date - 90, current_date - 1, interval '1 day') d
),
docs as (
  select
    delivered_at::date                       as day,
    count(*) filter (where versao = 1)       as first_filings,
    count(*) filter (where versao > 1)       as restatements
  from fnet_document
  where delivered_at >= (current_date - 90)::timestamp
    and delivered_at <  current_date::timestamp
  group by 1
)
select
  to_char(s.day, 'YYYY-MM-DD')                               as day,
  coalesce(d.first_filings, 0)                               as first_filings,
  coalesce(d.restatements, 0)                                as restatements,
  coalesce(d.first_filings, 0) + coalesce(d.restatements, 0) as documents
from spine s
left join docs d on d.day = s.day
order by s.day
