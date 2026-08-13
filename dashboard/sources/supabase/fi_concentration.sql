-- Single-holder concentration screen: the 25 FI funds whose largest quotaholder
-- owns the biggest share of net assets, at the latest perfil period.
--
-- pr_patrim_liq_maior_cotst is a CVM "PR_" field. The parser's `pct` coercion
-- deliberately does NOT rescale (src/parsers/mapping.py: "CVM ships raw fractions
-- or percentages; callers normalise downstream if needed"), so the value is
-- published in SOURCE UNITS and is shown that way here — rescaling it on a guess
-- would be fabrication. The page says so next to the table.
--
-- Same typed-column-then-raw-JSONB read as fi_investor_mix.sql: the column exists
-- in schema.sql but is not in the perfil FIELD_MAP, so the value normally lives in
-- the residual `raw`.
--
-- ZERO-ROW SAFETY: a one-row VALUES spine drives the query and the whole screen
-- hangs off a LEFT JOIN LATERAL, so an empty (or unmapped) cvm_fi_perfil returns
-- one all-NULL row rather than an empty parquet.
select
  x.cnpj                  as cnpj,
  x.fund_name             as fund_name,
  x.period                as period,
  x.largest_holder_share  as largest_holder_share,
  x.pl_mm                 as pl_mm,
  x.investors             as investors,
  x.credit_priv_share     as credit_priv_share
from (values (1)) as g(one)
left join lateral (
  with anchor as (
    select coalesce(max(period), current_date) as p_end
    from cvm_fi_perfil
  ),
  latest_fact as (
    select distinct on (f.cnpj)
      f.cnpj          as cnpj,
      f.vl_patrim_liq as vl_patrim_liq,
      f.nr_cotst      as nr_cotst
    from fact_fund_monthly f
    cross join anchor a
    where f.entity_type = 'fi'
      and f.period >= (a.p_end - interval '6 months')::date
    order by f.cnpj, f.period desc
  )
  select
    p.cnpj                                                   as cnpj,
    coalesce(d.fund_name, p.cnpj)                            as fund_name,
    p.period                                                 as period,
    coalesce(p.pr_patrim_liq_maior_cotst::numeric,
      case when p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PATRIM_LIQ_MAIOR_COTST', ',', '.')::numeric
      end)                                                   as largest_holder_share,
    lf.vl_patrim_liq / 1e6                                   as pl_mm,
    lf.nr_cotst                                              as investors,
    coalesce(p.pr_ativo_cred_priv::numeric,
      case when p.raw->>'PR_ATIVO_CRED_PRIV' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_ATIVO_CRED_PRIV', ',', '.')::numeric
      end)                                                   as credit_priv_share
  from cvm_fi_perfil p
  cross join anchor a
  left join dim_fund d on d.cnpj = p.cnpj and d.entity_type = 'fi'
  left join latest_fact lf on lf.cnpj = p.cnpj
  where p.period = a.p_end
  order by largest_holder_share desc nulls last, lf.vl_patrim_liq desc nulls last
  limit 25
) x on true
order by x.largest_holder_share desc nulls last, x.pl_mm desc nulls last
