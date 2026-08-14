select
  cnpj,
  fund_name,
  period,
  pl_mm,
  inad_pct as inad_num1
from fraud_screen_zombie_growth(null, 5, 1e6)
limit 20
