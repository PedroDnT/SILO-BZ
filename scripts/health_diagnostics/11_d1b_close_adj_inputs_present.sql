-- D1b PRECONDITION: is there anything to verify the factor convention against?
--
-- Diagnostic 09 (verify the convention) produced NO output on the 2026-08-31
-- run, and the step's own contract makes two very different causes look
-- identical: "a missing relation skips that file" and "the query ran and
-- matched nothing" both print nothing. This file exists to tell them apart,
-- because "we cannot verify the convention" and "we have no events to verify
-- it against" call for completely different work.
--
-- Counts only. If events_total is 0 the blocker is ingestion. If it is large
-- but with_both_sides is 0, the blocker is the ISIN join to the tape. If both
-- are healthy, diagnostic 09 was skipped for another reason and that is itself
-- the finding.
SELECT
    (SELECT count(*) FROM b3_corporate_event)                        AS events_total,
    (SELECT count(*) FROM b3_corporate_event WHERE event_class = 'stock')
                                                                     AS share_count_events,
    (SELECT count(DISTINCT isin) FROM b3_corporate_event)            AS distinct_isins,
    (SELECT count(*) FROM vw_b3_share_count_event)                   AS view_rows,
    (SELECT count(*) FROM vw_b3_share_count_event
      WHERE close_unit_before IS NOT NULL
        AND close_unit_after  IS NOT NULL)                           AS with_both_sides,
    -- Does the tape even know these ISINs? If this is 0 the join is the
    -- problem, not the event data.
    (SELECT count(DISTINCT e.isin)
       FROM b3_corporate_event e
      WHERE EXISTS (SELECT 1 FROM b3_cotahist b WHERE b.isin = e.isin))
                                                                     AS isins_seen_on_tape;
