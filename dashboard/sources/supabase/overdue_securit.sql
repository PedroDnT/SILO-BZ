select instrument_type, cnpj_securit, codigo_identificacao,
       data_vencimento, situacao, volume_mm, rating
from fraud_screen_overdue_securit(1e5)
limit 30
