-- /filings: what the newest FIDC informe restatements changed, field by field.
-- Reads the diff tables of migration 46 directly, with the same gate
-- api.fund_restatement_diff() applies: only a pair whose status is 'compared'
-- has diff rows, and that pair row carries the cnpjFundo link that made it.
-- (The api function needs one CNPJ or one document, so it cannot serve "the
-- latest across funds" in one call.)
--
-- Bounds: the 10 newest compared pairs that changed at least one field, at
-- most 20 fields each, so at most 200 rows.
--
-- Scope, as the diff job has it: the FIDC informe mensal only, restatements
-- delivered from 2026 on. Tab VIII (debtors) is not in the XML. old_value /
-- new_value are the text as printed (comma decimals); delta is set only on
-- numeric leaves. match_basis 'position' rows are approximate by construction.
--
-- Zero-row guard: union-all fallback emits one all-NULL row; the page filters it.
with pairs as (
  select pr.fnet_id, pr.prev_fnet_id, pr.cnpj, d.fund_name, d.reference_raw,
         d.versao, d.modalidade, d.delivered_at
  from fnet_document_pair pr
  join fnet_document d on d.fnet_id = pr.fnet_id
  where pr.status = 'compared'
    and pr.n_changed + pr.n_added + pr.n_removed > 0
  order by d.delivered_at desc, pr.fnet_id desc
  limit 10
),
fields as (
  select
    p.fnet_id, p.prev_fnet_id, p.cnpj, p.fund_name, p.reference_raw,
    p.versao, p.modalidade, p.delivered_at,
    x.field_path, x.block, x.leaf, x.change_kind, x.old_value, x.new_value,
    x.new_num - x.old_num as delta,
    x.match_basis,
    row_number() over (partition by p.fnet_id, p.prev_fnet_id order by x.field_path) as rn
  from pairs p
  join fnet_document_diff x
    on x.fnet_id = p.fnet_id
   and x.prev_fnet_id = p.prev_fnet_id
),
s as (
  select
    fnet_id,
    prev_fnet_id                                  as previous_fnet_id,
    cnpj,
    fund_name,
    reference_raw,
    versao,
    modalidade,
    to_char(delivered_at, 'YYYY-MM-DD HH24:MI')   as delivered_at,
    field_path,
    block,
    leaf,
    change_kind,
    old_value,
    new_value,
    delta,
    match_basis
  from fields
  where rn <= 20
  order by delivered_at desc, fnet_id desc, field_path
)
select * from s
union all
select null::bigint, null::bigint, null::text, null::text, null::text, null::int,
       null::text, null::text, null::text, null::text, null::text, null::text,
       null::text, null::text, null::numeric, null::text
where not exists (select 1 from s)
