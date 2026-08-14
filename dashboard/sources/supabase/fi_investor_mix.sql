-- FI investor mix over time (long format: one row per month per investor class),
-- from the NR_COTST_* / PR_PL_COTST_* split in cvm_fi_perfil (PERFIL_MENSAL).
--
-- Two measures per class, because they answer different questions:
--   holders_k    — how MANY investors of that type hold the fund (NR_COTST_*)
--   pl_share_num2 — how much of the industry's PL they hold  (PR_PL_COTST_*,
--                  weighted by each fund's own PL share, not a naive average)
-- A single private-banking cotista can hold more PL than ten thousand retail
-- ones, so headcount alone reads the industry backwards.
--
-- PROVENANCE / COVERAGE: every bucket below is now a typed column on
-- cvm_fi_perfil (migration 14) and mapped by src/parsers/field_maps/fi_perfil.py.
-- Months ingested BEFORE that change still carry the values only in the residual
-- `raw` JSONB, so each read is coalesce(typed_column, raw->>'CVM_HEADER'). When
-- neither is present the value is NULL — absent data is shown as absent, never
-- imputed.
--
-- ZERO-ROW SAFETY: a 24-month generate_series spine CROSS JOINed with a fixed
-- 12-row class list drives the output (288 rows, always), with the aggregate
-- LEFT JOINed on. An empty cvm_fi_perfil yields NULL counts, not an empty
-- parquet.
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
-- sort_order 1..7 keep the meaning they had before this file gained the
-- retail-individual / pension / foreign / other buckets, so existing chart
-- ordering is unchanged and the new classes append after them.
classes (investor_class, sort_order, is_retail) as (
  values
    ('Individuals - private banking', 1,  true),
    ('Corporates - retail',           2,  true),
    ('Corporates - private banking',  3,  false),
    ('Financial companies',           4,  false),
    ('Banks (own book)',              5,  false),
    ('Funds & investment clubs',      6,  false),
    ('Distributors',                  7,  false),
    ('Individuals - retail',          8,  true),
    ('Brokers & dealers',             9,  false),
    ('Pension & insurance',           10, false),
    ('Foreign investors',             11, false),
    ('Other',                         12, false)
),
per_fund as (
  select
    -- cvm_fi_perfil.period is the source DT_COMPTC, i.e. MONTH END (2025-12-31),
    -- while the spine above is first-of-month. Normalising here is what makes
    -- the join below match at all.
    date_trunc('month', p.period)::date as period,
    -- fund PL weight for the share-of-PL measure: PR_PL_COTST_* is a percentage
    -- OF THIS FUND's PL, so it can only be aggregated weighted by that PL.
    d.vl_patrim_liq as fund_pl,
    coalesce(p.nr_cotst_pf_pb::numeric,
      case when p.raw->>'NR_COTST_PF_PB' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PF_PB')::numeric end)                      as c_pf_pb,
    coalesce(p.nr_cotst_pf_varejo::numeric,
      case when p.raw->>'NR_COTST_PF_VAREJO' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PF_VAREJO')::numeric end)                  as c_pf_varejo,
    coalesce(p.nr_cotst_pj_nao_financ_varejo::numeric,
      case when p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PJ_NAO_FINANC_VAREJO')::numeric end)       as c_pj_varejo,
    coalesce(p.nr_cotst_pj_nao_financ_pb::numeric,
      case when p.raw->>'NR_COTST_PJ_NAO_FINANC_PB' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PJ_NAO_FINANC_PB')::numeric end)           as c_pj_pb,
    coalesce(p.nr_cotst_pj_financ::numeric,
      case when p.raw->>'NR_COTST_PJ_FINANC' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_PJ_FINANC')::numeric end)                  as c_pj_financ,
    coalesce(p.nr_cotst_banco::numeric,
      case when p.raw->>'NR_COTST_BANCO' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_BANCO')::numeric end)                      as c_banco,
    coalesce(p.nr_cotst_fi_clube::numeric,
      case when p.raw->>'NR_COTST_FI_CLUBE' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_FI_CLUBE')::numeric end)                   as c_clube,
    coalesce(p.nr_cotst_distrib::numeric,
      case when p.raw->>'NR_COTST_DISTRIB' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_DISTRIB')::numeric end)                    as c_distrib,
    coalesce(p.nr_cotst_corretora_distrib::numeric,
      case when p.raw->>'NR_COTST_CORRETORA_DISTRIB' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_CORRETORA_DISTRIB')::numeric end)          as c_corretora,
    coalesce(p.nr_cotst_eapc::numeric,
      case when p.raw->>'NR_COTST_EAPC' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_EAPC')::numeric end)                       as c_eapc,
    coalesce(p.nr_cotst_efpc::numeric,
      case when p.raw->>'NR_COTST_EFPC' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_EFPC')::numeric end)                       as c_efpc,
    coalesce(p.nr_cotst_rpps::numeric,
      case when p.raw->>'NR_COTST_RPPS' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_RPPS')::numeric end)                       as c_rpps,
    coalesce(p.nr_cotst_segur::numeric,
      case when p.raw->>'NR_COTST_SEGUR' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_SEGUR')::numeric end)                      as c_segur,
    coalesce(p.nr_cotst_capitaliz::numeric,
      case when p.raw->>'NR_COTST_CAPITALIZ' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_CAPITALIZ')::numeric end)                  as c_capitaliz,
    coalesce(p.nr_cotst_invnr::numeric,
      case when p.raw->>'NR_COTST_INVNR' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_INVNR')::numeric end)                      as c_invnr,
    coalesce(p.nr_cotst_outro::numeric,
      case when p.raw->>'NR_COTST_OUTRO' ~ '^[0-9]+$'
           then (p.raw->>'NR_COTST_OUTRO')::numeric end)                      as c_outro,
    coalesce(p.pr_pl_cotst_pf_pb::numeric,
      case when p.raw->>'PR_PL_COTST_PF_PB' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PF_PB', ',', '.')::numeric end)  as s_pf_pb,
    coalesce(p.pr_pl_cotst_pf_varejo::numeric,
      case when p.raw->>'PR_PL_COTST_PF_VAREJO' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PF_VAREJO', ',', '.')::numeric end) as s_pf_varejo,
    coalesce(p.pr_pl_cotst_pj_nao_financ_varejo::numeric,
      case when p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_VAREJO' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_VAREJO', ',', '.')::numeric end) as s_pj_varejo,
    coalesce(p.pr_pl_cotst_pj_nao_financ_pb::numeric,
      case when p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_PB' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PJ_NAO_FINANC_PB', ',', '.')::numeric end) as s_pj_pb,
    coalesce(p.pr_pl_cotst_pj_financ::numeric,
      case when p.raw->>'PR_PL_COTST_PJ_FINANC' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_PJ_FINANC', ',', '.')::numeric end) as s_pj_financ,
    coalesce(p.pr_pl_cotst_banco::numeric,
      case when p.raw->>'PR_PL_COTST_BANCO' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_BANCO', ',', '.')::numeric end)  as s_banco,
    coalesce(p.pr_pl_cotst_fi_clube::numeric,
      case when p.raw->>'PR_PL_COTST_FI_CLUBE' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_FI_CLUBE', ',', '.')::numeric end) as s_clube,
    coalesce(p.pr_pl_cotst_distrib::numeric,
      case when p.raw->>'PR_PL_COTST_DISTRIB' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_DISTRIB', ',', '.')::numeric end) as s_distrib,
    coalesce(p.pr_pl_cotst_corretora_distrib::numeric,
      case when p.raw->>'PR_PL_COTST_CORRETORA_DISTRIB' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_CORRETORA_DISTRIB', ',', '.')::numeric end) as s_corretora,
    coalesce(p.pr_pl_cotst_eapc::numeric,
      case when p.raw->>'PR_PL_COTST_EAPC' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_EAPC', ',', '.')::numeric end)   as s_eapc,
    coalesce(p.pr_pl_cotst_efpc::numeric,
      case when p.raw->>'PR_PL_COTST_EFPC' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_EFPC', ',', '.')::numeric end)   as s_efpc,
    coalesce(p.pr_pl_cotst_rpps::numeric,
      case when p.raw->>'PR_PL_COTST_RPPS' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_RPPS', ',', '.')::numeric end)   as s_rpps,
    coalesce(p.pr_pl_cotst_segur::numeric,
      case when p.raw->>'PR_PL_COTST_SEGUR' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_SEGUR', ',', '.')::numeric end)  as s_segur,
    coalesce(p.pr_pl_cotst_capitaliz::numeric,
      case when p.raw->>'PR_PL_COTST_CAPITALIZ' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_CAPITALIZ', ',', '.')::numeric end) as s_capitaliz,
    coalesce(p.pr_pl_cotst_invnr::numeric,
      case when p.raw->>'PR_PL_COTST_INVNR' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_INVNR', ',', '.')::numeric end)  as s_invnr,
    coalesce(p.pr_pl_cotst_outro::numeric,
      case when p.raw->>'PR_PL_COTST_OUTRO' ~ '^[0-9]+([.,][0-9]+)?$'
           then replace(p.raw->>'PR_PL_COTST_OUTRO', ',', '.')::numeric end)  as s_outro
  from cvm_fi_perfil p
  cross join anchor a
  -- fact_fund_monthly is keyed on first-of-month; cvm_fi_perfil.period is the
  -- source DT_COMPTC (month end), hence the date_trunc. Funds with no FI NAV
  -- that month simply contribute NULL weight and drop out of pl_base.
  left join fact_fund_monthly d
    on  d.cnpj        = p.cnpj
    and d.entity_type = 'fi'
    and d.period      = date_trunc('month', p.period)::date
  where p.period between (date_trunc('month', a.p_end) - interval '23 months')::date
                     and a.p_end
),
mix as (
  select
    period                              as period,
    sum(c_pf_pb)                        as pf_pb,
    sum(c_pf_varejo)                    as pf_varejo,
    sum(c_pj_varejo)                    as pj_varejo,
    sum(c_pj_pb)                        as pj_pb,
    sum(c_pj_financ)                    as pj_financ,
    sum(c_banco)                        as banco,
    sum(c_clube)                        as clube,
    sum(c_distrib)                      as distrib,
    sum(c_corretora)                    as corretora,
    sum(coalesce(c_eapc, 0) + coalesce(c_efpc, 0) + coalesce(c_rpps, 0)
        + coalesce(c_segur, 0) + coalesce(c_capitaliz, 0))               as pensao,
    sum(c_invnr)                        as invnr,
    sum(c_outro)                        as outro,
    -- PL-weighted shares (percent of total PL of the funds that reported both
    -- a share and a PL that month). CVM populates the whole PR_PL_COTST_* block
    -- together — 24,979 of 24,979 rows in perfil_mensal_fi_202512 — so testing a
    -- few of the buckets is enough to tell "reported" from "not reported".
    sum(fund_pl) filter (
      where fund_pl is not null
        and (s_pf_pb is not null or s_pf_varejo is not null
             or s_invnr is not null or s_outro is not null)
    )                                                                    as pl_base,
    sum(s_pf_pb      * fund_pl)         as w_pf_pb,
    sum(s_pf_varejo  * fund_pl)         as w_pf_varejo,
    sum(s_pj_varejo  * fund_pl)         as w_pj_varejo,
    sum(s_pj_pb      * fund_pl)         as w_pj_pb,
    sum(s_pj_financ  * fund_pl)         as w_pj_financ,
    sum(s_banco      * fund_pl)         as w_banco,
    sum(s_clube      * fund_pl)         as w_clube,
    sum(s_distrib    * fund_pl)         as w_distrib,
    sum(s_corretora  * fund_pl)         as w_corretora,
    sum((coalesce(s_eapc, 0) + coalesce(s_efpc, 0) + coalesce(s_rpps, 0)
         + coalesce(s_segur, 0) + coalesce(s_capitaliz, 0)) * fund_pl)   as w_pensao,
    sum(s_invnr      * fund_pl)         as w_invnr,
    sum(s_outro      * fund_pl)         as w_outro
  from per_fund
  group by period
)
select
  m.period          as period,
  c.investor_class  as investor_class,
  c.sort_order      as sort_order,
  c.is_retail       as is_retail,
  case c.sort_order
    when 1  then x.pf_pb
    when 2  then x.pj_varejo
    when 3  then x.pj_pb
    when 4  then x.pj_financ
    when 5  then x.banco
    when 6  then x.clube
    when 7  then x.distrib
    when 8  then x.pf_varejo
    when 9  then x.corretora
    when 10 then x.pensao
    when 11 then x.invnr
    when 12 then x.outro
  end / 1e3         as holders_k,
  round(
    case c.sort_order
      when 1  then x.w_pf_pb
      when 2  then x.w_pj_varejo
      when 3  then x.w_pj_pb
      when 4  then x.w_pj_financ
      when 5  then x.w_banco
      when 6  then x.w_clube
      when 7  then x.w_distrib
      when 8  then x.w_pf_varejo
      when 9  then x.w_corretora
      when 10 then x.w_pensao
      when 11 then x.w_invnr
      when 12 then x.w_outro
    end / nullif(x.pl_base, 0)
  , 2)              as pl_share_num2
from months m
cross join classes c
left join mix x on x.period = m.period
order by m.period, c.sort_order
