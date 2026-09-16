-- The originators that sell receivables to the most FIDCs, at the latest
-- complete period, from informe tab I (cvm_fidc_cedente, migration 38).
--
-- Tab I names the nine largest cedentes of each block by their own CPF/CNPJ
-- and their share OF THAT BLOCK (A = receivables acquired with substantial
-- retention of risks and benefits by the originator, B = without). The block
-- totals are not ingested, so a share cannot be turned into reais here: this
-- table counts FUNDS per originator and reports the largest share it holds
-- in any single fund. It never sums shares across funds — a percent of one
-- fund's block plus a percent of another's is not a number.
--
-- The originator's name comes ONLY from cia_company (listed companies, keyed
-- by CNPJ) and its tickers from the published FCA map; an unlisted originator
-- is shown by CNPJ, never matched by name. Identifiers were checksum-verified
-- at ingest (placeholders dropped), so every row here is a real CPF/CNPJ.
--
-- SHARE CAVEAT: PR_CEDENTE is a raw CVM percentage field and carries the same
-- garbage the tranche percentage fields do — 9.1% of filled slots in 2026-07
-- are above 100 (max 19,771; 20 million in 2024-12). The warehouse stores it
-- as filed; this source reads a share only inside [0, 100] (NULL otherwise,
-- never clamped to 100) and prints how many slots it set aside per
-- originator, so the page shows the dirt instead of hiding it.
--
-- ZERO-ROW SAFETY: one-row `row_guard` LEFT JOINed with ON TRUE.
with latest as (
  select max(period) as period
    from cvm_fidc_cedente
   where period <= latest_complete_period('fidc')
),
originators as (
  select
    c.cpf_cnpj_cedente,
    c.period,
    count(distinct c.cnpj)                                          as n_funds,
    count(distinct c.cnpj) filter (where c.bloco = 'A')              as n_funds_block_a,
    count(distinct c.cnpj) filter (where c.seq = 1)                  as n_rank1,
    max(c.pr_cedente) filter (where c.pr_cedente between 0 and 100)  as max_share,
    count(*) filter (where c.pr_cedente < 0 or c.pr_cedente > 100)   as n_share_outliers
  from cvm_fidc_cedente c
  join latest l on c.period = l.period
  group by c.cpf_cnpj_cedente, c.period
),
row_guard as (
  select 1 as one
)
select
  coalesce(cia.denom_cia, o.cpf_cnpj_cedente)          as originator,
  o.cpf_cnpj_cedente                                   as cedente_id,
  t.tickers,
  o.period,
  o.n_funds,
  o.n_funds_block_a,
  o.n_rank1,
  round(o.max_share, 1)                                as max_share_num1,
  o.n_share_outliers
from row_guard g
left join originators o on true
left join cia_company cia
  on cia.cnpj_cia = o.cpf_cnpj_cedente
left join lateral (
  select string_agg(vt.codneg, ', ' order by vt.codneg) as tickers
  from vw_company_ticker vt
  where vt.is_active and vt.cnpj_cia = o.cpf_cnpj_cedente
) t on true
order by o.n_funds desc nulls last, o.n_rank1 desc nulls last, o.max_share desc nulls last
limit 20
