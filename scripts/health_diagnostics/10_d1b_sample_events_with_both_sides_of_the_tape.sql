-- D1b sample events with both sides of the tape
SELECT issuing_company, label, last_date_prior, factor,
  round(close_unit_before, 4) AS before_, round(close_unit_after, 4) AS after_,
  round(close_unit_before / NULLIF(close_unit_after, 0), 4) AS price_ratio
  FROM vw_b3_share_count_event
  WHERE close_unit_before IS NOT NULL AND close_unit_after IS NOT NULL
  ORDER BY last_date_prior DESC LIMIT 20;
