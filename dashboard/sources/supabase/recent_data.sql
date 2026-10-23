-- /recent: the newest data per dataset, read from api.coverage(), the same
-- freshness contract the public API serves. One row per coverage() dataset.
--
-- Two questions sit side by side and are never merged into one verdict:
--   * landed_at: when OUR ingest last succeeded for that source (status ok,
--     from cvm_ingest_log). An old landed_at is a pipeline question.
--   * as_of / complete_through: how far the SOURCE has published. CVM files
--     monthly data 1-2 months in arrears and FIP yearly, so an old as_of is
--     usually the filing calendar, not an outage.
-- No red/green status is derived: cadences differ per source (daily B3 tape,
-- weekly FII sweep, monthly CVM, yearly FIP), and one threshold across them
-- would flag normal lags as failures. /ops owns the operator verdicts.
--
-- landed_at is shown in UTC-3 (America/Sao_Paulo, owner's display rule); the
-- stored value is timestamptz and is not changed.
--
-- days_since_landed and days_behind are counted from current_date at build
-- time, so they age with the snapshot; the page states the build time.
--
-- ZERO-ROW SAFETY: coverage() returns a fixed set of literal dataset rows, so
-- it is never empty; the NULL row below guards a future signature change.
with c as (
  select dataset, source, as_of, complete_through, newest_period, landed_at, notes
  from api.coverage()
)
select
  dataset,
  source,
  as_of,
  complete_through,
  newest_period,
  (landed_at at time zone 'America/Sao_Paulo')::timestamp(0)               as landed_at_brt,
  round(extract(epoch from (now() - landed_at))::numeric / 86400.0, 1)     as days_since_landed,
  (current_date - as_of)                                                   as days_behind,
  notes
from c
union all
select null::text, null::text, null::date, null::date, null::date, null::timestamp(0), null::numeric, null::int, null::text
where not exists (select 1 from c)
order by source, dataset
