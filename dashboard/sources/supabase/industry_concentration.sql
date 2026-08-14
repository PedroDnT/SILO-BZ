-- Concentration of each fund family at its own latest reported period.
--
-- market_concentration() (src/store/analytical/09_analytical_functions.sql)
-- takes a single entity type, so the five families are supplied as a literal
-- driver list and the function is called per-row with LEFT JOIN LATERAL. The
-- function aggregates without GROUP BY and therefore always yields exactly one
-- row (all-NULL when that family has no data), which keeps this source at a
-- fixed 5 rows — a 0-row source would write a zero-byte parquet and break the
-- build.
--
-- Passing NULL as the period means "that family's own latest period", so the
-- families are each measured on their freshest data rather than forced onto a
-- shared date they may not all report.
--
-- hhi is on the 0-10000 scale (sum of squared AUM shares x 10000); the top-N
-- shares are converted from fractions to percent here, not in a format code.
with entities (entity_type, family) as (
  values
    ('fi',     'FI (open-ended funds)'),
    ('fidc',   'FIDC (receivables)'),
    ('fii',    'FII (real estate)'),
    ('fiagro', 'FIAGRO (agribusiness)'),
    ('fip',    'FIP (private equity)')
)
select
  e.family,
  e.entity_type,
  mc.period,
  round(mc.hhi, 1)                  as hhi,
  round(100.0 * mc.top5_share, 1)   as top5_num1,
  round(100.0 * mc.top10_share, 1)  as top10_num1,
  round(100.0 * mc.top20_share, 1)  as top20_num1,
  mc.n_funds
from entities e
left join lateral market_concentration(e.entity_type, null) mc on true
order by mc.hhi desc nulls last
