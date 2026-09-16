-- Participação mensal por tipo de investidor e mercado (B3's own monthly table).
--
-- This is B3's published monthly aggregate, not a derivation — so unlike the
-- daily series it needs no first-differencing and carries no basis caveat. It
-- is still forward-only: past months return "Nenhum resultado", so the history
-- grows one month per run.
select
  m.reference_month,
  m.investor_type,
  m.market,
  m.valor_brl / 1e9 as valor_brl_bn,
  m.participacao_pct as participacao
from b3_investor_participation_monthly m
order by m.reference_month desc, m.market, m.valor_brl desc
