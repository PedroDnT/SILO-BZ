-- /filings late-filer screen. Definition: api.screen_late_filers()
-- (src/store/analytical/25_api_filing_screens.sql). That function IS the one
-- definition (no public screen sits under it), so this source calls it rather
-- than restating the deadline rule; it only formats, orders and caps.
--
-- Arguments are the function's defaults, written out so the page can state
-- them: 12 reference months ending at the newest month whose deadline has
-- passed, 5 days past the deadline counts as late, 2 late months to flag,
-- both families (FII and FIDC).
--
-- Zero-row guard: an empty source is a 0-byte parquet that kills the whole
-- build; the union-all fallback emits one all-NULL row, which the page filters.
with s as (
  select
    cnpj,
    fund_family,
    fund_name,
    to_char(window_from, 'YYYY-MM')         as window_from,
    to_char(window_to, 'YYYY-MM')           as window_to,
    informes,
    informes_late,
    max_days_late,
    median_lag_days                         as median_lag_days_num1,
    to_char(last_late_reference, 'YYYY-MM') as last_late_reference
  from api.screen_late_filers(12, null, 5, 2, null)
  order by informes_late desc, max_days_late desc, cnpj
  limit 50
)
select * from s
union all
select null::text, null::text, null::text, null::text, null::text,
       null::bigint, null::bigint, null::int, null::numeric, null::text
where not exists (select 1 from s)
