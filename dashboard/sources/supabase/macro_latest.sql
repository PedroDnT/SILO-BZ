-- Latest observation of each headline BACEN series, plus the through-date of
-- each of the three source tables.
--
-- Every expression is a scalar sub-query and there is no FROM clause, so this
-- returns exactly one row no matter how empty bacen_sgs / bacen_ptax /
-- bacen_expectativas are. A 0-row source makes Evidence write a zero-byte
-- parquet and the whole build then dies reading it back, so single-row shape is
-- the guarantee, not a convenience.
--
-- Units are as published by BACEN and are NOT converted here:
--   432 SELIC meta = % a.a.   ·   11/12 SELIC diária & CDI = % a.d.
--   433/189/188 IPCA/IGP-M/INPC = % change in the month   ·   1 USDBRL = BRL per USD
select
  (select value from bacen_sgs where series_code = 432 order by reference_date desc limit 1) as selic_meta_num2,
  (select value from bacen_sgs where series_code = 12  order by reference_date desc limit 1) as cdi_num2,
  (select value from bacen_sgs where series_code = 433 order by reference_date desc limit 1) as ipca_mes_num2,
  (select value from bacen_sgs where series_code = 189 order by reference_date desc limit 1) as igpm_mes_num2,
  (select value from bacen_sgs where series_code = 188 order by reference_date desc limit 1) as inpc_mes_num2,
  (select sell_rate from bacen_ptax where currency = 'USD' order by reference_date desc limit 1) as usd_brl,
  (select sell_rate from bacen_ptax where currency = 'EUR' order by reference_date desc limit 1) as eur_brl,
  (select median from bacen_expectativas
    where endpoint_name = 'ExpectativasMercadoAnuais' and indicador = 'IPCA'
    order by reference_date desc limit 1) as focus_ipca_median_num2,
  (select median from bacen_expectativas
    where endpoint_name = 'ExpectativasMercadoAnuais' and indicador = 'Selic'
    order by reference_date desc limit 1) as focus_selic_median_num2,
  (select max(reference_date) from bacen_sgs)           as sgs_through,
  (select max(reference_date) from bacen_ptax)          as ptax_through,
  (select max(reference_date) from bacen_expectativas)  as focus_through,
  (select count(*) from bacen_sgs)                      as sgs_rows,
  (select count(*) from bacen_ptax)                     as ptax_rows,
  (select count(*) from bacen_expectativas)             as focus_rows
