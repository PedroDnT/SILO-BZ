-- What moved the IPCA: IBGE's nine expenditure groups for the latest month
-- held, with the WEIGHT each carries in the basket and the contribution that
-- weight × variation makes to the headline.
--
-- Source: ibge_ipca_item_monthly (IBGE SIDRA 7060), level 1 — the groups.
-- BACEN's SGS has the same nine variations but NOT the weights, so this is
-- the one place on the page where "what moved it" is answerable.
--
-- Driven from a literal list of the nine groups in IBGE's order, LEFT JOINed
-- to the data, so the source always returns exactly 9 rows and a group that
-- has not landed shows blank rather than disappearing (or emptying the
-- parquet). The month is the latest one that has any level-1 row, so all nine
-- come from the same release.
--
-- Units: weight_num2 is the % of the basket (the general index is 100);
-- change_month_num2 and change_12m_num2 are % as IBGE publishes them;
-- contribution_num2 = weight × change / 100, in percentage points of the
-- headline — the only derived number here. The nine contributions sum to the
-- headline to rounding because the groups partition the basket.
with latest as (
  select max(reference_month) as reference_month
  from ibge_ipca_item_monthly
  where level = 1
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
  g.item_number,
  g.group_name,
  l.reference_month,
  i.peso_mensal                                         as weight_num2,
  i.variacao_mensal                                     as change_month_num2,
  case when i.peso_mensal is not null and i.variacao_mensal is not null
       then round(i.peso_mensal * i.variacao_mensal / 100, 2)
  end                                                   as contribution_num2,
  i.variacao_acum_12m                                   as change_12m_num2
from groups g
cross join latest l
left join ibge_ipca_item_monthly i
       on i.level = 1
      and i.item_number = g.item_number
      and i.reference_month = l.reference_month
order by g.item_number
