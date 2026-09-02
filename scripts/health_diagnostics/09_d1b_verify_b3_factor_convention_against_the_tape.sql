-- D1b VERIFY B3 factor convention against the tape
--
-- The whole reason no adjusted price series ships yet. B3 publishes a `factor`
-- per event but its meaning is not uniform across labels, and an adjustment
-- built on a guessed convention silently rescales every historical price.
-- price_ratio (close_unit_before / close_unit_after) is what the tape actually
-- did across the entitlement date; whichever candidate reproduces it per label
-- IS the convention.
--
-- TWO CANDIDATES, from the shape of the published values:
--   direct   ratio = factor            (factor is the share multiplier itself)
--   percent  ratio = 1 + factor/100    (factor is new shares issued per 100 held)
--
-- WHY THIS REPORTS A DISTRIBUTION, NOT AN AVERAGE. The previous version took
-- avg(ratio/candidate), which one bad event moves arbitrarily far — a name that
-- drifted 20% between the two prints, or had a second event in the gap, drags
-- the mean off a convention that fits everything else. What decides this is the
-- BULK: the median, and the share of events the candidate reproduces within a
-- tolerance. A convention that lands 90%+ of its label inside ±5% is a
-- convention; one whose median is right but whose hit rate is 40% is a
-- coincidence, and the difference is invisible in a mean.
--
-- ±5% is deliberately loose. These are closes on two different sessions, so a
-- real day of price movement sits inside the tolerance and must not be read as
-- the convention failing.
WITH ev AS (
    SELECT label,
           factor,
           close_unit_before / NULLIF(close_unit_after, 0) AS price_ratio
      FROM vw_b3_share_count_event
     WHERE close_unit_before IS NOT NULL
       AND close_unit_after  IS NOT NULL
       AND close_unit_after  > 0
       AND factor IS NOT NULL
       AND factor > 0
), scored AS (
    SELECT label,
           price_ratio,
           price_ratio / factor                    AS vs_direct,
           price_ratio / NULLIF(1 + factor / 100.0, 0) AS vs_percent
      FROM ev
)
SELECT label,
       count(*)                                              AS events,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY price_ratio)::numeric, 4)
                                                             AS median_price_ratio,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_direct)::numeric, 4)
                                                             AS median_vs_direct,
       round(100.0 * avg((abs(vs_direct  - 1) <= 0.05)::int), 1)
                                                             AS pct_within_5_direct,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_percent)::numeric, 4)
                                                             AS median_vs_percent,
       round(100.0 * avg((abs(vs_percent - 1) <= 0.05)::int), 1)
                                                             AS pct_within_5_percent
  FROM scored
 GROUP BY label
 ORDER BY events DESC;
