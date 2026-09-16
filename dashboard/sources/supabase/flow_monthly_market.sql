-- Participação mensal por tipo de investidor e mercado (B3's own monthly table).
--
-- This is B3's published monthly aggregate, not a derivation — so unlike the
-- daily series it needs no first-differencing and carries no basis caveat. It
-- is still forward-only: past months return "Nenhum resultado", so the history
-- grows one month per run.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    m.reference_month,
    m.investor_type,
    m.market,
    m.valor_brl / 1e9 as valor_brl_bn,
    m.participacao_pct as participacao
  from b3_investor_participation_monthly m
  order by m.reference_month desc, m.market, m.valor_brl desc
)
select * from rows_
union all
select null::date, null::text, null::text, null::numeric, null::numeric(12,4)
where not exists (select 1 from rows_)
