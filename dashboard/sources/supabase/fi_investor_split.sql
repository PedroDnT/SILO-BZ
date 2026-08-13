-- Retail vs institutional rotation in the FI investor base.
--
-- Retail  = individuals (retail) + individuals (private banking)
--           + non-financial corporates (retail)
-- Instit. = corporates (private banking) + financial companies + banks
--           + brokers/dealers + funds/clubs + distributors
--           + pension & insurance (EAPC/EFPC/RPPS/SEGUR/CAPITALIZ)
--           + foreign investors (INVNR) + other
--
-- NR_COTST_PF_VAREJO — CVM's mass-retail individual bucket, and by far the
-- largest one — used to be missing from the schema, so "retail" here was only a
-- modelled subset. Migration 14 added it (and the other nine missing buckets),
-- so this source now covers all 16 investor types CVM publishes.
--
-- HEADCOUNT vs MONEY: retail_pct counts investors; retail_pl_pct is their share
-- of PL (PR_PL_COTST_*, weighted by each fund's own PL). They diverge by design —
-- retail is most of the headcount and a minority of the money — and reading only
-- the first is how a fund that is 99% one institution looks "retail".
--
-- Same typed-column-then-raw-JSONB read as fi_investor_mix.sql: months ingested
-- before migration 14 carry the values only in the residual `raw`.
--
-- ZERO-ROW SAFETY: driven by a 24-month generate_series spine; the aggregate is
-- LEFT JOINed on, so the source always returns 24 rows.
with anchor as (
  select coalesce(
           max(period),
           date_trunc('month', current_date)::date
         ) as p_end
  from cvm_fi_perfil
),
months as (
  select generate_series(
           date_trunc('month', a.p_end) - interval '23 months',
           date_trunc('month', a.p_end),
           interval '1 month'
         )::date as period
  from anchor a
),
per_fund as (
  select
    -- month END in the source (DT_COMPTC) vs first-of-month in the spine above
    date_trunc('month', p.period)::date as period,
    v.retail    as retail,
    v.instit    as instit,
    v.any_split as any_split,
    d.vl_patrim_liq                       as fund_pl,
    w.retail_share                        as retail_share,
    w.any_share                           as any_share
  from cvm_fi_perfil p
  cross join anchor a
  left join fact_fund_monthly d
    on  d.cnpj        = p.cnpj
    and d.entity_type = 'fi'
    and d.period      = date_trunc('month', p.period)::date
  cross join lateral (
    select
      coalesce(p.nr_cotst_pf_pb::numeric,
        case when p.raw->>'NR_COTST_PF_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PF_PB')::numeric end)                    as c_pf_pb,
      coalesce(p.nr_cotst_pf_varejo::numeric,
        case when p.raw->>'NR_COTST_PF_VAREJO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PF_VAREJO')::numeric end)                as c_pf_varejo,
      coalesce(p.nr_cotst_pj_nao_financ_varejo::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO')::numeric end)     as c_varejo,
      coalesce(p.nr_cotst_pj_nao_financ_pb::numeric,
        case when p.raw->>'NR_COTST_PJ_NAO_FINANC_PB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_NAO_FINANC_PB')::numeric end)         as c_pj_pb,
      coalesce(p.nr_cotst_pj_financ::numeric,
        case when p.raw->>'NR_COTST_PJ_FINANC' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_PJ_FINANC')::numeric end)                as c_financ,
      coalesce(p.nr_cotst_banco::numeric,
        case when p.raw->>'NR_COTST_BANCO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_BANCO')::numeric end)                    as c_banco,
      coalesce(p.nr_cotst_fi_clube::numeric,
        case when p.raw->>'NR_COTST_FI_CLUBE' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_FI_CLUBE')::numeric end)                 as c_clube,
      coalesce(p.nr_cotst_distrib::numeric,
        case when p.raw->>'NR_COTST_DISTRIB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_DISTRIB')::numeric end)                  as c_distrib,
      coalesce(p.nr_cotst_corretora_distrib::numeric,
        case when p.raw->>'NR_COTST_CORRETORA_DISTRIB' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_CORRETORA_DISTRIB')::numeric end)        as c_corretora,
      coalesce(p.nr_cotst_eapc::numeric,
        case when p.raw->>'NR_COTST_EAPC' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_EAPC')::numeric end)                     as c_eapc,
      coalesce(p.nr_cotst_efpc::numeric,
        case when p.raw->>'NR_COTST_EFPC' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_EFPC')::numeric end)                     as c_efpc,
      coalesce(p.nr_cotst_rpps::numeric,
        case when p.raw->>'NR_COTST_RPPS' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_RPPS')::numeric end)                     as c_rpps,
      coalesce(p.nr_cotst_segur::numeric,
        case when p.raw->>'NR_COTST_SEGUR' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_SEGUR')::numeric end)                    as c_segur,
      coalesce(p.nr_cotst_capitaliz::numeric,
        case when p.raw->>'NR_COTST_CAPITALIZ' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_CAPITALIZ')::numeric end)                as c_capitaliz,
      coalesce(p.nr_cotst_invnr::numeric,
        case when p.raw->>'NR_COTST_INVNR' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_INVNR')::numeric end)                    as c_invnr,
      coalesce(p.nr_cotst_outro::numeric,
        case when p.raw->>'NR_COTST_OUTRO' ~ '^[0-9]+$'
             then (p.raw->>'NR_COTST_OUTRO')::numeric end)                    as c_outro,
      coalesce(p.pr_pl_cotst_pf_pb::numeric,
        case when p.raw->>'PR_PL_COTST_PF_PB' ~ '^[0-9]+([.,][0-9]+)?$'
             then replace(p.raw->>'PR_PL_COTST_PF_PB', ',', '.')::numeric end)      as s_pf_pb,
      coalesce(p.pr_pl_cotst_pf_varejo::numeric,
        case when p.raw->>'PR_PL_COTST_PF_VAREJO' ~ '^[0-9]+([.,][0-9]+)?$'
             then replace(p.raw->>'PR_PL_COTST_PF_VAREJO', ',', '.')::numeric end)  as s_pf_varejo,
      coalesce(p.pr_pl_cotst_pj_nao_financ_varejo::numeric,
        case when p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+([.,][0-9]+)?$'
             then replace(p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_VAREJO', ',', '.')::numeric end) as s_varejo
  ) c
  cross join lateral (
    select
      coalesce(c.c_pf_pb, 0) + coalesce(c.c_pf_varejo, 0) + coalesce(c.c_varejo, 0) as retail,
      coalesce(c.c_pj_pb, 0) + coalesce(c.c_financ, 0) + coalesce(c.c_banco, 0)
        + coalesce(c.c_clube, 0) + coalesce(c.c_distrib, 0) + coalesce(c.c_corretora, 0)
        + coalesce(c.c_eapc, 0) + coalesce(c.c_efpc, 0) + coalesce(c.c_rpps, 0)
        + coalesce(c.c_segur, 0) + coalesce(c.c_capitaliz, 0)
        + coalesce(c.c_invnr, 0) + coalesce(c.c_outro, 0)                     as instit,
      (c.c_pf_pb is not null or c.c_pf_varejo is not null or c.c_varejo is not null
        or c.c_pj_pb is not null or c.c_financ is not null or c.c_banco is not null
        or c.c_clube is not null or c.c_distrib is not null)                  as any_split
  ) v
  cross join lateral (
    select
      coalesce(c.s_pf_pb, 0) + coalesce(c.s_pf_varejo, 0) + coalesce(c.s_varejo, 0) as retail_share,
      -- no institutional counterpart is derived here: 100 - retail would be an
      -- assumption about a source that can leave buckets blank.
      (c.s_pf_pb is not null or c.s_pf_varejo is not null or c.s_varejo is not null) as any_share
  ) w
  where p.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
),
agg as (
  select
    period                                            as period,
    sum(retail)                                       as retail,
    sum(instit)                                       as instit,
    count(*)                                          as n_funds,
    count(*) filter (where any_split)                 as n_funds_with_split,
    sum(retail_share * fund_pl) filter (where any_share and fund_pl is not null) as w_retail,
    sum(fund_pl)                 filter (where any_share and fund_pl is not null) as pl_base
  from per_fund
  group by period
)
select
  m.period                                                          as period,
  a.retail / 1e3                                                    as retail_k,
  a.instit / 1e3                                                    as institutional_k,
  round(100.0 * a.retail / nullif(a.retail + a.instit, 0), 1)       as retail_pct,
  round(a.w_retail / nullif(a.pl_base, 0), 1)                       as retail_pl_pct,
  a.n_funds                                                         as n_funds,
  a.n_funds_with_split                                              as n_funds_with_split
from months m
left join agg a on a.period = m.period
order by m.period
