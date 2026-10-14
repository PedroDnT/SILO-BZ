-- /filings silent-filer screen. Definition: api.screen_silent_filers()
-- (src/store/analytical/25_api_filing_screens.sql), the one definition; this
-- source only formats, scales, orders and caps.
--
-- Arguments are the function's defaults, written out so the page can state
-- them: 3 to 24 complete months with no periodic informe, all four families
-- (FI, FIDC, FII, FIAGRO). FIP files annually and is not screened. Silence is
-- measured in CVM's own datasets against latest_complete_period(), never
-- today. The FNET column is context only.
--
-- Zero-row guard: union-all fallback emits one all-NULL row; the page filters it.
with s as (
  select
    cnpj,
    fund_family,
    fund_name,
    registry_status,
    to_char(last_filed_period, 'YYYY-MM-DD')      as last_filed_period,
    to_char(complete_through, 'YYYY-MM-DD')       as complete_through,
    months_silent,
    reports_filed,
    registry_nav / 1e6                            as registry_nav_mm,
    to_char(registry_nav_date, 'YYYY-MM-DD')      as registry_nav_date,
    to_char(fnet_last_delivered_at, 'YYYY-MM-DD') as fnet_last_delivered
  from api.screen_silent_filers(3, 24, null)
  order by registry_nav desc nulls last, months_silent, cnpj
  limit 50
)
select * from s
union all
select null::text, null::text, null::text, null::text, null::text, null::text,
       null::int, null::bigint, null::numeric, null::text, null::text
where not exists (select 1 from s)
