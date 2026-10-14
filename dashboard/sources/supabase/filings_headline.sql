-- /filings headline tiles: the FNET register over the last 30 complete days.
--
-- Zero-row safety: a no-GROUP-BY aggregate, so this is always exactly one row.
-- An empty window reads 0, the truthful answer, not a 0-byte parquet.
--
-- delivered_at is São Paulo local time as printed (no AT TIME ZONE). Dates are
-- to_char strings: a NULL date renders as the Unix epoch in Evidence, and a
-- timestamp would be shifted by the browser's zone.
select
  to_char(current_date - 30, 'YYYY-MM-DD')                 as window_from,
  to_char(current_date - 1,  'YYYY-MM-DD')                 as window_to,
  count(*)                                                 as documents,
  count(*) filter (where versao > 1)                       as restatements,
  count(*) filter (where versao > 1 and modalidade = 'RC') as restatements_rc,
  round(100.0 * count(*) filter (where versao > 1) / nullif(count(*), 0), 1)
                                                           as restated_share_num1,
  to_char(max(delivered_at), 'YYYY-MM-DD HH24:MI')         as last_delivered_at
from fnet_document
where delivered_at >= (current_date - 30)::timestamp
  and delivered_at <  current_date::timestamp
