-- /holdings: one row per kind and month from mv_fund_holdings_monthly
-- (analytical file 30), the month totals (key NULL): funds filing, assets,
-- R$ held and the same-economic-group part. `complete` marks the months up to
-- the last complete one per kind: CVM's newest CDA months fill in late (from
-- 2026-06 about half the funds, issue #476), so a month counts only when its
-- n_funds reaches 90% of the median of the 12 months before it, the rule
-- rates_ntnb_fund_holdings.sql uses.
--
-- ZERO-ROW SAFETY: a one-row driver LEFT JOINs the result.
with tot as (
  select kind, period, n_funds, n_assets, vl_total, vl_related
  from mv_fund_holdings_monthly
  where key is null
),
anchor as (
  select m.kind, max(m.period) as p_end
  from tot m
  where m.n_funds >= 0.9 * (
    select percentile_cont(0.5) within group (order by p.n_funds)
    from tot p
    where p.kind = m.kind
      and p.period <  m.period
      and p.period >= m.period - interval '12 months'
  )
  group by m.kind
),
result as (
  select
    t.kind,
    t.period,
    t.n_funds,
    t.n_assets,
    t.vl_total / 1e9                         as total_bn,
    t.vl_related / 1e9                       as related_bn,
    t.vl_related / nullif(t.vl_total, 0)     as related_share_num2,
    t.period <= a.p_end                      as complete,
    a.p_end
  from tot t
  left join anchor a on a.kind = t.kind
)
select r.*
from (select 1) as one
left join result r on true
order by r.kind, r.period
