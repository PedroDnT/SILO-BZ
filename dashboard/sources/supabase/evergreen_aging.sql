select cnpj, fund_name, months_observed, min_longtail_pct, max_longtail_pct
from fraud_screen_evergreen_aging(12, 70, 10)
limit 20
