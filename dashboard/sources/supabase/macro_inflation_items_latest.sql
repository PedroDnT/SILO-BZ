-- The drill under "What moved the IPCA": every subgroup (level 2), item
-- (level 3) and subitem (level 4) of IBGE's IPCA tree for the latest month,
-- tagged with the group it belongs to so the page can filter by group.
--
-- Source: ibge_ipca_item_monthly (IBGE SIDRA 7060). The month is the same one
-- macro_inflation_groups_latest.sql uses (the latest with any level-1 row), so
-- the drill reconciles with the group bars above it.
--
-- Group membership is IBGE's own numbering: an item's number starts with its
-- group's digit (1101002 is under 1101, under 11, under group 1). Nothing is
-- matched by name.
--
-- Driven from the literal list of the nine groups and LEFT JOINed to the
-- items, so the source always returns at least 9 rows (one blank row per
-- group when nothing has landed) and never writes a zero-byte parquet.
--
-- Units: weight_num2 is IBGE's % of the whole basket; change_month_num2 and
-- change_12m_num2 are % as IBGE publishes them; contribution_num2 = weight x
-- change / 100, in p.p. of the headline, the only derived number. Levels nest,
-- so contributions sum within one level, never across levels.
with latest as (
  select max(reference_month) as reference_month
  from ibge_ipca_item_monthly
  where level = 1
),
groups (group_number, group_name) as (
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
  g.group_number,
  g.group_name,
  l.reference_month,
  i.level,
  case i.level when 2 then 'Subgroup' when 3 then 'Item' when 4 then 'Subitem' end as level_name,
  i.item_number,
  i.item_name,
  i.peso_mensal                                         as weight_num2,
  i.variacao_mensal                                     as change_month_num2,
  case when i.peso_mensal is not null and i.variacao_mensal is not null
       then round(i.peso_mensal * i.variacao_mensal / 100, 2)
  end                                                   as contribution_num2,
  i.variacao_acum_12m                                   as change_12m_num2
from groups g
cross join latest l
left join ibge_ipca_item_monthly i
       on i.level between 2 and 4
      and left(i.item_number, 1) = g.group_number
      and i.reference_month = l.reference_month
order by g.group_number, i.item_number
