-- Which cvm_fii_mensal subtypes and fields are actually populated.
--
-- The /fii page used only doc_subtype = 'complemento' until the payout sections
-- were added; this table makes the other two subtypes' coverage visible so a
-- blank payout column can be read as "not filed / not mapped" rather than "zero
-- distributions".
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL around the GROUP BY.
select
  x.doc_subtype       as doc_subtype,
  x.n_rows            as n_rows,
  x.n_funds           as n_funds,
  x.first_period      as first_period,
  x.latest_period     as latest_period,
  x.with_pl           as with_pl,
  x.with_ativo        as with_ativo,
  x.with_cotas        as with_cotas,
  x.with_vpc          as with_vpc,
  x.with_rendimentos  as with_rendimentos
from (values (1)) as g(one)
left join lateral (
  select
    m.doc_subtype                                                     as doc_subtype,
    count(*)                                                          as n_rows,
    count(distinct m.cnpj)                                            as n_funds,
    min(m.period)                                                     as first_period,
    max(m.period)                                                     as latest_period,
    count(*) filter (where m.vl_patrim_liq is not null)               as with_pl,
    count(*) filter (where m.vl_ativo is not null)                    as with_ativo,
    count(*) filter (where m.cotas_emitidas is not null)              as with_cotas,
    count(*) filter (where m.vl_patrimonial_cotas is not null)        as with_vpc,
    count(*) filter (where m.rendimentos_distribuir is not null)      as with_rendimentos
  from cvm_fii_mensal m
  group by m.doc_subtype
) x on true
order by x.n_rows desc nulls last
