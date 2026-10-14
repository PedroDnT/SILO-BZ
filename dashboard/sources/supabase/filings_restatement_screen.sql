-- /filings restatement screen. Definition: api.screen_restatements()
-- (src/store/analytical/25_api_filing_screens.sql), the one definition; this
-- source only renames, orders and caps.
--
-- Arguments are the function's defaults, written out so the page can state
-- them: a 12-month delivery window ending today, at least 3 re-filings
-- (versao > 1) that are at least 20% of the fund's documents, RE and RC both.
-- restatement_pct is a percentage (0..100), so it is aliased *_num1, never _pct.
--
-- Zero-row guard: union-all fallback emits one all-NULL row; the page filters it.
with s as (
  select
    cnpj,
    tipo_fundo,
    fund_name,
    documents,
    restatements,
    restatements_re,
    restatements_rc,
    restatement_pct                         as restated_share_num1,
    to_char(last_restated_at, 'YYYY-MM-DD') as last_restated
  from api.screen_restatements(12, null, 3, 20, null)
  order by restatements desc, cnpj
  limit 50
)
select * from s
union all
select null::text, null::text, null::text, null::bigint, null::bigint, null::bigint,
       null::bigint, null::numeric, null::text
where not exists (select 1 from s)
