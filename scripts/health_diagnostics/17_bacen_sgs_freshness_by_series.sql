-- BACEN SGS FRESHNESS BY SERIES: which series are landing, and when they last did
--
-- Check 4c in health.yml fails when the DAILY series (CDI 12, SELIC_DIARIA 11)
-- are older than MAX_SGS_AGE_DAYS. It deliberately ignores the monthly and
-- quarterly series, because IPCA (433) goes ~40 days between observations and
-- PIB (4380) longer, and a gate that fires every month on a series that is
-- simply not due yet is an alarm people learn to ignore.
--
-- This file is the view the gate does not give: one row per configured series
-- with its last observation, how old it is, and how many observations landed
-- in the last 45 days. A monthly series with `last_45d = 0` is worth a look
-- once its publication date has passed (IPCA: around the 10th of the next
-- month); a daily series with `last_45d < 20` means the refresh has been
-- skipping days.
--
-- Background: on 2026-09-03 every SGS series had `last_45d` frozen because
-- python-bcb raised on IPCA's 404 (August not published) and the pipeline
-- dropped all ten series together, then swallowed the error. The fetch is now
-- one request per series (#198) so an absent month empties one series only.
--
-- Read-only; reads bacen_sgs alone (small, indexed on (series_code, reference_date)).

SELECT series_name,
       series_code,
       max(reference_date)                                   AS last_observation,
       (CURRENT_DATE - max(reference_date))::int             AS age_days,
       count(*) FILTER (WHERE reference_date >= CURRENT_DATE - 45) AS last_45d,
       count(*)                                              AS total_rows,
       CASE
         WHEN series_code IN (11, 12) THEN 'daily'
         WHEN series_code IN (1, 21619, 25, 432) THEN 'daily-ish'
         WHEN series_code IN (433, 188, 189) THEN 'monthly'
         WHEN series_code = 4380 THEN 'monthly (GDP proxy)'
         ELSE 'unclassified'
       END                                                   AS cadence
  FROM bacen_sgs
 GROUP BY series_name, series_code
 ORDER BY age_days DESC, series_name;
