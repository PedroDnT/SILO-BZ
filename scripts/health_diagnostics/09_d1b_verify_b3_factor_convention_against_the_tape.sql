-- D1b VERIFY B3 factor convention against the tape
-- The whole reason no adjusted price series ships yet. B3 publishes a
-- `factor` per event but its meaning is NOT uniform across labels
-- (DESDOBRAMENTO 100.0 vs GRUPAMENTO 0.1). price_ratio is what the
-- tape actually did across the entitlement date; whichever candidate
-- reproduces it per label IS the convention. Until this returns
-- consistent numbers, quotes stay unadjusted.
SELECT label,
  count(*)                                              AS events,
  round(avg(factor), 4)                                 AS avg_factor,
  round(avg(close_unit_before / NULLIF(close_unit_after, 0)), 4)
  AS avg_price_ratio,
  round(avg((close_unit_before / NULLIF(close_unit_after, 0))
  / NULLIF(factor, 0)), 6)                    AS ratio_over_factor,
  round(avg((close_unit_before / NULLIF(close_unit_after, 0))
  / NULLIF(1 + factor / 100.0, 0)), 6)        AS ratio_over_pct_convention
  FROM vw_b3_share_count_event
  WHERE close_unit_before IS NOT NULL AND close_unit_after IS NOT NULL
  GROUP BY label ORDER BY events DESC;
