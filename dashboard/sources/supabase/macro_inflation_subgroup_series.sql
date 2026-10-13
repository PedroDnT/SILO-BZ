-- History under the drill: each IPCA subgroup's (level 2) contribution to the
-- headline, last 36 months, tagged with its group so the page can filter by
-- the group picked in the drill.
--
-- Source: ibge_ipca_item_monthly (IBGE SIDRA 7060), level 2. Group membership
-- is IBGE's numbering (subgroup 51 is under group 5), never the name.
--
-- Shape: the month spine CROSS JOINed to the nine groups, LEFT JOINed to the
-- subgroups, so every (month, group) has at least one row and the source can
-- never be empty (a 0-row source breaks the build).
--
-- SPINE END: the page stacks the subgroups of one group, so it ends at the
-- last month whose nine groups are all complete — the same p_end as
-- macro_inflation_contrib_series.sql, so the two charts share an x-axis.
-- least() ignores a NULL max(), so an empty table falls back to the last
-- ended month.
--
-- Units: contribution_num2 = weight x change / 100, p.p. of the headline.
-- The subgroups of a group sum to that group's contribution to rounding.
with anchor as (
  select least(
           (date_trunc('month', current_date) - interval '1 month')::date,
           (select max(reference_month)
              from (select reference_month
                      from ibge_ipca_item_monthly
                     where level = 1
                       and peso_mensal is not null
                       and variacao_mensal is not null
                     group by reference_month
                    having count(*) = 9) full_months)
         ) as p_end
),
spine as (
  select generate_series(
           (select p_end from anchor) - interval '35 months',
           (select p_end from anchor),
           interval '1 month'
         )::date as period
),
groups (group_number) as (
  values ('1'), ('2'), ('3'), ('4'), ('5'), ('6'), ('7'), ('8'), ('9')
)
select
  sp.period,
  g.group_number,
  i.item_number,
  i.item_name,
  i.peso_mensal                                         as weight_num2,
  i.variacao_mensal                                     as change_month_num2,
  case when i.peso_mensal is not null and i.variacao_mensal is not null
       then round(i.peso_mensal * i.variacao_mensal / 100, 2)
  end                                                   as contribution_num2
from spine sp
cross join groups g
left join ibge_ipca_item_monthly i
       on i.level = 2
      and left(i.item_number, 1) = g.group_number
      and i.reference_month = sp.period
order by sp.period, g.group_number, i.item_number
