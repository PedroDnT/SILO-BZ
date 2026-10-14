-- /filings: restatements (versao > 1) delivered in the last 30 complete days,
-- by FNET document type. Reads the FNET register directly (migrations 42, 46).
--
-- linked = the document has a cnpjFundo link, so it is known as a fund's;
-- the per-fund sweep is fortnightly, so a recent restatement is often not
-- linked yet. diffed = a fnet_document_pair row with status 'compared'
-- exists for it (the diff job covers the FIDC informe mensal only).
-- RC = CVM required the re-filing; RE = voluntary.
--
-- Bounded: the 15 types with the most restatements.
-- Zero-row guard: union-all fallback emits one all-NULL row; the page filters it.
with restated as (
  select d.fnet_id, d.tipo_documento, d.modalidade
  from fnet_document d
  where d.versao > 1
    and d.delivered_at >= (current_date - 30)::timestamp
    and d.delivered_at <  current_date::timestamp
),
s as (
  select
    coalesce(nullif(btrim(r.tipo_documento), ''), '(no type)') as tipo_documento,
    count(*)                                             as restatements,
    count(*) filter (where r.modalidade = 'RE')          as restatements_re,
    count(*) filter (where r.modalidade = 'RC')          as restatements_rc,
    count(*) filter (where exists (
      select 1 from fnet_document_filter l
      where l.fnet_id = r.fnet_id and l.filter_name = 'cnpjFundo'))
                                                         as linked,
    count(*) filter (where exists (
      select 1 from fnet_document_pair p
      where p.fnet_id = r.fnet_id and p.status = 'compared'))
                                                         as diffed
  from restated r
  group by 1
  order by count(*) desc, 1
  limit 15
)
select * from s
union all
select null::text, null::bigint, null::bigint, null::bigint, null::bigint, null::bigint
where not exists (select 1 from s)
