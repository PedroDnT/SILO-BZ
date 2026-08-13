-- Honest coverage counter for the FII property explorer.
--
-- Counts how many cvm_fii_periodic rows actually resolve a building name and a
-- percentual_imovel_pl (typed column OR residual `raw` key — see
-- fii_property_explorer.sql for why the value can be in either), and how many of
-- those cross the single-asset threshold. If these read zero, the explorer below
-- is empty because the property detail is not in the ingested member of the
-- INF_TRIMESTRAL zip — not because Brazilian FIIs own no buildings.
--
-- ZERO-ROW SAFETY: aggregate without GROUP BY → exactly one row, always.
select
  count(*)                                                              as periodic_rows,
  count(distinct p.cnpj)                                                as funds_with_periodic_filing,
  max(p.period_year)::text                                              as latest_period_year,
  count(*) filter (where coalesce(p.nome_imovel, r.nome_imovel) is not null)
                                                                        as rows_with_property_name,
  count(*) filter (where coalesce(p.percentual_imovel_pl::numeric,
      case when r.pct_txt ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(r.pct_txt, ',', '.')::numeric end) is not null)
                                                                        as rows_with_pl_share,
  count(*) filter (where coalesce(p.percentual_imovel_pl::numeric,
      case when r.pct_txt ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(r.pct_txt, ',', '.')::numeric end) > 50)
                                                                        as rows_single_asset_over_50pct
from cvm_fii_periodic p
cross join lateral (
  select
    max(t.v) filter (where t.k = 'nome_imovel')            as nome_imovel,
    max(t.v) filter (where t.k in ('percentual_imovel_pl',
                                   'percentual_imovel_sobre_pl')) as pct_txt
  from (
    select lower(kv.key) as k, kv.value as v
    from jsonb_each_text(p.raw) kv
  ) t
) r
