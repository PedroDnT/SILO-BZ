-- DORMANT FUNDS: registered, "em funcionamento", and nothing moving through them
--
-- The question: are there more parked fund CNPJs — filing every day, zero
-- investors, zero money in or out — than there are companies listed on B3?
--
-- It is not idle curiosity. A fund that exists, files, and holds nobody's money
-- is a vehicle waiting to be used, and the cost of standing one up later is the
-- part someone has already paid. Counting them is the same job as the
-- fraud_screen_* views: say what the filings actually show.
--
-- Definitions, stated because each one is a choice:
--
--   "dormant"  — over the window below, every daily filing has zero captação,
--                zero resgate, and no quotaholder. NOT "small": exactly zero on
--                all three. A fund with one investor and no trades is asleep;
--                a fund with no investor at all is unused.
--   "window"   — the last 3 complete months of cvm_fi_diario. Short on purpose:
--                the table is the largest in the warehouse and this file runs
--                inside the 90 s diagnostics budget. Three months of total
--                stillness is already the signal; a longer window would raise
--                the bar, not lower it, so this count is a FLOOR.
--   "listed"   — deliberately three different answers, because "empresa na
--                bolsa" is ambiguous and the gap between the readings is
--                itself the finding: distinct cash tickers in the most recent
--                B3 session, distinct issuers behind them, and registered
--                non-cancelled companhias abertas.
--
-- Read block 3 before quoting any ratio: comparing a fund COUNT to a ticker
-- COUNT is comparing two different kinds of thing, and the numerator here is
-- CNPJs while a listed company can carry several tickers.

-- 1. The fund universe, by registry status.
SELECT status,
       count(*)                                     AS cnpjs,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
  FROM dim_fund
 GROUP BY status
 ORDER BY cnpjs DESC;

-- 2. Dormant FI classes over the last 3 complete months.
--    bounded to the partition range so this never scans the whole table.
WITH bounds AS (
    SELECT date_trunc('month', max(dt_comptc))::date              AS cur_month,
           (date_trunc('month', max(dt_comptc)) - INTERVAL '3 months')::date AS win_start
      FROM cvm_fi_diario
     WHERE dt_comptc >= (CURRENT_DATE - INTERVAL '400 days')
), per_fund AS (
    SELECT d.cnpj,
           count(*)                        AS days_filed,
           sum(coalesce(d.captc_dia, 0))   AS captacao,
           sum(coalesce(d.resg_dia, 0))    AS resgate,
           max(coalesce(d.nr_cotst, 0))    AS max_cotistas,
           max(coalesce(d.vl_patrim_liq, 0)) AS max_nav
      FROM cvm_fi_diario d, bounds b
     WHERE d.dt_comptc >= b.win_start
       AND d.dt_comptc <  b.cur_month
     GROUP BY d.cnpj
)
SELECT
    (SELECT win_start FROM bounds)                              AS window_from,
    (SELECT cur_month FROM bounds)                              AS window_to,
    count(*)                                                    AS fi_classes_filing,
    count(*) FILTER (WHERE captacao = 0 AND resgate = 0
                       AND max_cotistas = 0)                    AS dormant_no_investor,
    count(*) FILTER (WHERE captacao = 0 AND resgate = 0
                       AND max_cotistas = 0 AND max_nav = 0)    AS dormant_and_empty,
    count(*) FILTER (WHERE captacao = 0 AND resgate = 0
                       AND max_cotistas > 0)                    AS no_flow_but_invested,
    round(100.0 * count(*) FILTER (WHERE captacao = 0 AND resgate = 0
                                     AND max_cotistas = 0)
          / nullif(count(*), 0), 1)                             AS pct_dormant
  FROM per_fund;

-- 3. What "listed on B3" comes to, three ways.
--    vw_b3_quote_vista is the cash board (tpmerc 010); the parent table is
--    option-heavy and would inflate every count here.
SELECT
    (SELECT count(DISTINCT codneg)
       FROM vw_b3_quote_vista
      WHERE trade_date = (SELECT max(trade_date) FROM vw_b3_quote_vista))
        AS cash_tickers_last_session,
    (SELECT count(DISTINCT left(isin, 12))
       FROM vw_b3_quote_vista
      WHERE trade_date = (SELECT max(trade_date) FROM vw_b3_quote_vista)
        AND isin IS NOT NULL AND isin <> '')
        AS distinct_isins_last_session,
    -- coalesce, not a bare <>: NULL <> 'CANCELADA' is NULL, so a company with
    -- no recorded situação would be dropped from a count of everything that is
    -- not cancelled — the one row you would most want to see.
    (SELECT count(*) FROM cia_company
      WHERE coalesce(situacao, '') <> 'CANCELADA')
        AS registered_companies_not_cancelled,
    (SELECT count(*) FROM cia_company WHERE situacao IS NULL)
        AS companies_with_no_situacao,
    (SELECT max(trade_date) FROM vw_b3_quote_vista)
        AS last_b3_session;
