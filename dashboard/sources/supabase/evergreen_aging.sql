select
  cnpj,
  fund_name,
  months_observed,
  min_longtail_pct as min_longtail_num1,
  max_longtail_pct as max_longtail_num1
from fraud_screen_evergreen_aging(12, 70, 10)
limit 20
