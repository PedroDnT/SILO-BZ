-- D2.5 FI/FIDC fund counts around 2025-05 (Res.175 subclass phase-in?)
SELECT entity_type, period, n_funds
  FROM mv_period_completeness
  WHERE entity_type IN ('fi','fidc','fii')
  AND period BETWEEN DATE '2024-11-01' AND DATE '2025-10-31'
  ORDER BY entity_type, period;
