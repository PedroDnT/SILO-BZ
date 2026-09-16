-- MAIORES TAXAS DE ALUGUEL — top 20 by the borrower's annualized rate.
--
-- taxa_tomador_pct is B3's trade-count-weighted average for the session,
-- re-weighted across markets by registered quantity in
-- fact_short_interest_daily. Markets with zero registered quantity publish a
-- nominal rate on no business and are already excluded there, which is what
-- stops a dormant BDR from topping the table at 20% a.a. on one contract.
--
-- The size floor does the same job for the position: a high rate on a
-- R$50k book is noise, not demand.
--
-- ZERO-ROW SAFETY: this source is empty until the first daily run lands, and a
-- zero-row source writes the 0-byte parquet that kills the whole Evidence build
-- (same guard as b3_top_volume.sql / delinquency_trend.sql). That window is not
-- hypothetical here — B3 keeps no archive, so on a fresh deploy these tables are
-- empty until the cron has run once. Hence the union-all sentinel row.
with rows_ as (
  select
    row_number() over (order by s.taxa_tomador_pct desc) as rank,
    s.codneg                                             as ticker,
    s.asset_name,
    s.taxa_tomador_pct as taxa_tomador_aa,
    s.taxa_doador_pct as taxa_doador_aa,
    s.short_brl,
    s.pct_float,
    s.num_contratos
  from fact_short_interest_daily s
  where s.trade_date = (select max(trade_date) from fact_short_interest_daily)
    and s.taxa_tomador_pct is not null
    and s.categoria in ('SHARES', 'UNIT')
    and s.short_brl >= 1000000
  order by s.taxa_tomador_pct desc
  limit 20
)
select * from rows_
union all
select null::bigint, null::text, null::text, null::numeric, null::numeric, null::numeric, null::numeric, null::bigint
where not exists (select 1 from rows_)
