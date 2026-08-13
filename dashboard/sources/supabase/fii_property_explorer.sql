-- FII property explorer — the individual buildings behind the funds.
--
-- Reads cvm_fii_imovel, the property register CVM ships as its own member of the
-- INF_TRIMESTRAL zip. This query previously read cvm_fii_periodic + a scan of its
-- residual `raw`, which was wrong twice over: the fetcher was silently ingesting
-- the *alienação* (property-disposal) member, so those rows described buildings
-- being SOLD, and the periodic table's (cnpj, doc_type, period_year) grain cannot
-- hold one row per building anyway.
--
-- UNITS: pr_* fields are published by CVM without a documented scale (fraction vs
-- percent varies by file), so they are shown unconverted and labelled "source
-- units" rather than being multiplied on a guess. pr_imovel_total_investido is a
-- share of the fund's total INVESTED assets — not of its net assets (PL).
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL, so an empty
-- cvm_fii_imovel still returns a row (a zero-row source writes a 0-byte parquet
-- and kills the entire build).
select
  x.fund_name          as fund_name,
  x.cnpj               as cnpj,
  x.data_referencia    as data_referencia,
  x.classe             as classe,
  x.nome_imovel        as nome_imovel,
  x.endereco           as endereco,
  x.area               as area,
  x.numero_unidades    as numero_unidades,
  x.pct_invested       as pct_invested,
  x.vacancia           as vacancia,
  x.inadimplencia      as inadimplencia,
  x.concentration_flag as concentration_flag
from (values (1)) as g(one)
left join lateral (
  select
    coalesce(d.fund_name, i.cnpj)  as fund_name,
    i.cnpj                         as cnpj,
    i.data_referencia              as data_referencia,
    i.classe                       as classe,
    i.nome_imovel                  as nome_imovel,
    i.endereco                     as endereco,
    i.area                         as area,
    i.numero_unidades              as numero_unidades,
    i.pr_imovel_total_investido    as pct_invested,
    i.pr_vacancia                  as vacancia,
    i.pr_inadimplencia             as inadimplencia,
    case
      when i.pr_imovel_total_investido is null then null
      when i.pr_imovel_total_investido > 50    then 'single asset > 50% of invested'
      else 'diversified'
    end                            as concentration_flag
  from cvm_fii_imovel i
  left join dim_fund d
    on d.cnpj = i.cnpj and d.entity_type = 'fii'
  where i.data_referencia = (select max(data_referencia) from cvm_fii_imovel)
  order by i.pr_imovel_total_investido desc nulls last, i.area desc nulls last, i.cnpj
  limit 200
) x on true
order by x.pct_invested desc nulls last, x.area desc nulls last, x.cnpj
