-- What moved the IPCA, month by month: each of IBGE's nine expenditure groups'
-- contribution to the headline, last 36 months. The history behind
-- macro_inflation_groups_latest.sql, built the same way.
--
-- Source: ibge_ipca_item_monthly (IBGE SIDRA 7060), level 1 — the groups.
-- Long format: one row per (month, group). The month spine is CROSS JOINed to
-- the literal list of the nine groups and LEFT JOINed to the data, so the
-- source is a fixed 36 x 9 = 324 rows and never collapses to zero (a 0-row
-- source writes a zero-byte parquet and breaks the build).
--
-- SPINE END (dashboard/README.md, "Spine rule"): the chart is stacked, so a
-- month is drawn only when EVERY band is there. p_end = least(last ended
-- month, last month with all nine groups carrying both a weight and a
-- change). least() ignores a NULL max(), so an empty table falls back to the
-- last ended month and the rows come back blank.
--
-- Units: contribution_num2 = weight x change / 100, in percentage points of
-- the headline — the same and only derived number as the latest-month source.
-- weight_num2 is IBGE's % of the basket; change_month_num2 is IBGE's % change
-- in the month. The nine contributions sum to the month's IPCA to rounding.
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
groups (item_number, group_name) as (
  values
    ('1', '1. Alimentação e bebidas'),
    ('2', '2. Habitação'),
    ('3', '3. Artigos de residência'),
    ('4', '4. Vestuário'),
    ('5', '5. Transportes'),
    ('6', '6. Saúde e cuidados pessoais'),
    ('7', '7. Despesas pessoais'),
    ('8', '8. Educação'),
    ('9', '9. Comunicação')
)
select
  sp.period,
  g.item_number,
  g.group_name,
  i.peso_mensal                                         as weight_num2,
  i.variacao_mensal                                     as change_month_num2,
  case when i.peso_mensal is not null and i.variacao_mensal is not null
       then round(i.peso_mensal * i.variacao_mensal / 100, 2)
  end                                                   as contribution_num2
from spine sp
cross join groups g
left join ibge_ipca_item_monthly i
       on i.level = 1
      and i.item_number = g.item_number
      and i.reference_month = sp.period
order by sp.period, g.item_number
