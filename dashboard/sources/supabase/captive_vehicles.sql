select cnpj, fund_name, latest_period, pl_mm, min_investors
from fraud_screen_captive_vehicles(3, 10, 5e7)
limit 20
