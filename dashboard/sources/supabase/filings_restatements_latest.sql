-- /filings: the 50 newest restatements (versao > 1) LINKED to a fund, delivered
-- in the last 30 complete days, read from the FNET register directly
-- (migrations 42 and 46).
--
-- Not api.fund_restatements(): at its default 30-day window it already returns
-- more than 1000 rows and REFUSES (22023), and a refusing source kills the
-- build. This source reads the same tables with a hard LIMIT instead.
--
-- Fund identity is the cnpjFundo link only (fnet_document_filter), never
-- fund_name, which is FNET's label for reading. One row per (document, link),
-- as the api serves it. Only linked documents are listed: the per-fund sweep
-- is fortnightly, so the newest re-filings are nearly all unlinked (measured
-- 2026-10-14: 50 of the 50 newest), and a list of them would never show a fund
-- or a diff. Unlinked re-filings are counted in filings_restatements_by_type.
-- The diff columns come from fnet_document_pair, the pairing the diff job
-- stored (src/pipeline/fnet_diff.py), not a re-derived one: the pair row for
-- this document and link, the compared one first. NULL = not diffed, which is
-- every document outside the FIDC informe mensal.
--
-- delivered_at is São Paulo local time as printed: to_char, no AT TIME ZONE.
-- current_date is the database's (UTC) date; the production build runs in the
-- morning, when it equals the São Paulo date.
-- Zero-row guard: union-all fallback emits one all-NULL row; the page filters it.
with restated as (
  select d.fnet_id, l.filter_value as cnpj, d.fund_name, d.tipo_documento,
         d.reference_raw, d.versao, d.modalidade, d.delivered_at
  from fnet_document d
  join fnet_document_filter l
    on l.fnet_id = d.fnet_id
   and l.filter_name = 'cnpjFundo'
  where d.versao > 1
    and d.delivered_at >= (current_date - 30)::timestamp
    and d.delivered_at <  current_date::timestamp
  order by d.delivered_at desc, d.fnet_id desc, l.filter_value
  limit 50
),
s as (
  select
    r.fnet_id,
    r.cnpj,
    tf.tipo_fundo,
    r.fund_name,
    r.tipo_documento,
    r.reference_raw,
    r.versao,
    r.modalidade,
    to_char(r.delivered_at, 'YYYY-MM-DD HH24:MI')           as delivered_at,
    p.prev_fnet_id                                          as previous_fnet_id,
    p.status                                                as diff_status,
    case when p.status = 'compared'
         then p.n_changed + p.n_added + p.n_removed end     as fields_changed,
    'https://fnet.bmfbovespa.com.br/fnet/publico/downloadDocumento?id='
      || r.fnet_id::text                                    as source_url
  from restated r
  left join lateral (
    select string_agg(
             case t.filter_value when '1' then 'FII' when '2' then 'FIDC' when '3' then 'ETF' end,
             ',' order by t.filter_value) as tipo_fundo
    from fnet_document_filter t
    where t.fnet_id = r.fnet_id
      and t.filter_name = 'tipoFundo'
      and t.filter_value in ('1', '2', '3')
  ) tf on true
  left join lateral (
    select pr.prev_fnet_id, pr.status, pr.n_changed, pr.n_added, pr.n_removed
    from fnet_document_pair pr
    where pr.fnet_id = r.fnet_id
      and pr.cnpj = r.cnpj
    order by (pr.status = 'compared') desc, pr.compared_at desc nulls last, pr.prev_fnet_id desc nulls last
    limit 1
  ) p on true
  order by r.delivered_at desc, r.fnet_id desc, r.cnpj
)
select * from s
union all
select null::bigint, null::text, null::text, null::text, null::text, null::text,
       null::int, null::text, null::text, null::bigint, null::text, null::int, null::text
where not exists (select 1 from s)
