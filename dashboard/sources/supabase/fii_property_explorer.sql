-- FII property explorer: the individual buildings behind the funds, from
-- cvm_fii_periodic.
--
-- PROVENANCE / COVERAGE — read before trusting a blank cell. The property columns
-- (nome_imovel, endereco, area, numero_unidades, percentual_imovel_pl) are
-- declared on cvm_fii_periodic in schema.sql, but the periodic FIELD_MAP
-- (src/parsers/field_maps/fii_periodic.py) maps only cnpj and data_referencia —
-- every other CSV header lands in the residual `raw` JSONB. On top of that, the
-- fetcher pulls the main member of the INF_TRIMESTRAL zip
-- (csv_name_pattern = inf_trimestral_fii_{year}.csv, src/fetchers/cvm_config.py);
-- CVM ships the per-building detail in a SEPARATE member of the same zip. So a
-- property row resolves only when the value is present in one of those two
-- places. This query reads the typed column first, then falls back to a
-- case-insensitive scan of `raw` — and leaves the cell NULL when neither has it.
-- Nothing is inferred from the fund's other filings.
--
-- ZERO-ROW SAFETY: one-row VALUES spine + LEFT JOIN LATERAL, so an empty
-- cvm_fii_periodic (or one with no property fields at all) still returns a row.
select
  x.fund_name             as fund_name,
  x.cnpj                  as cnpj,
  x.doc_type              as doc_type,
  x.period_year           as period_year,
  x.data_referencia       as data_referencia,
  x.nome_imovel           as nome_imovel,
  x.endereco              as endereco,
  x.area                  as area,
  x.numero_unidades       as numero_unidades,
  x.pct_of_pl             as pct_of_pl,
  x.single_asset_flag     as single_asset_flag
from (values (1)) as g(one)
left join lateral (
  select
    coalesce(d.fund_name, p.cnpj)                          as fund_name,
    p.cnpj                                                 as cnpj,
    p.doc_type                                             as doc_type,
    p.period_year::text                                    as period_year,
    p.data_referencia                                      as data_referencia,
    coalesce(p.nome_imovel, r.nome_imovel)                 as nome_imovel,
    coalesce(p.endereco, r.endereco)                       as endereco,
    coalesce(p.area::numeric,
      case when r.area_txt ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(r.area_txt, ',', '.')::numeric end)          as area,
    coalesce(p.numero_unidades::numeric,
      case when r.unidades_txt ~ '^[0-9]+$'
           then r.unidades_txt::numeric end)                         as numero_unidades,
    coalesce(p.percentual_imovel_pl::numeric,
      case when r.pct_txt ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(r.pct_txt, ',', '.')::numeric end)           as pct_of_pl,
    case
      when coalesce(p.percentual_imovel_pl::numeric,
             case when r.pct_txt ~ '^[0-9]+([.,][0-9]+)?$'
                  then replace(r.pct_txt, ',', '.')::numeric end) is null then null
      when coalesce(p.percentual_imovel_pl::numeric,
             case when r.pct_txt ~ '^[0-9]+([.,][0-9]+)?$'
                  then replace(r.pct_txt, ',', '.')::numeric end) > 50 then 'single asset > 50% of PL'
      else 'diversified'
    end                                                    as single_asset_flag
  from cvm_fii_periodic p
  left join dim_fund d
    on d.cnpj = p.cnpj and d.entity_type = 'fii'
  cross join lateral (
    select
      max(t.v) filter (where t.k = 'nome_imovel')                              as nome_imovel,
      max(t.v) filter (where t.k = 'endereco')                                 as endereco,
      max(t.v) filter (where t.k in ('area', 'area_m2', 'area_bruta_locavel')) as area_txt,
      max(t.v) filter (where t.k in ('numero_unidades', 'num_unidades'))       as unidades_txt,
      max(t.v) filter (where t.k in ('percentual_imovel_pl',
                                     'percentual_imovel_sobre_pl'))            as pct_txt
    from (
      select lower(kv.key) as k, kv.value as v
      from jsonb_each_text(p.raw) kv
    ) t
  ) r
  order by pct_of_pl desc nulls last, p.period_year desc, p.cnpj
  limit 200
) x on true
order by x.pct_of_pl desc nulls last, x.period_year desc nulls last, x.cnpj
