-- Executed checks for api.risk_decompose (44_api_risk_decompose.sql, catalog
-- v90). The Python tests pin the SQL text; this proves the function DOES the
-- right thing on rows. Synthetic tickers (RSKA3, the stock; RSKF3, a filler
-- that trades every session), inside a transaction that is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/risk_decompose_behaviour.sql

BEGIN;

-- 200 weekday sessions from 2024-01-02. IBOV and IFNC follow fixed waves; the
-- stock loads 0.9 on IBOV and 0.5 on the sector move, plus its own wave.
-- Session 100 is a -12% IBOV shock. RSKA3 does not trade on sessions 50, 51, 52.
CREATE TEMP TABLE rk_spine ON COMMIT DROP AS
SELECT k, d::date AS d,
       CASE WHEN k = 100 THEN -0.12 ELSE 0.010 * sin(k * 1.3) + 0.004 * cos(k * 0.7) END AS m,
       0.006 * sin(k * 2.1) AS sx,
       0.008 * cos(k * 3.7) AS e
FROM (SELECT row_number() OVER (ORDER BY d) AS k, d
      FROM generate_series(DATE '2024-01-02', DATE '2024-12-31', '1 day') d
      WHERE extract(isodow FROM d) < 6) x
WHERE k <= 200;

CREATE TEMP TABLE rk_levels ON COMMIT DROP AS
SELECT k, d, m,
       1.1 * m + sx AS s,
       0.9 * m + 0.5 * sx + e AS r,
       100000 * exp(sum(ln(1 + CASE WHEN k = 1 THEN 0 ELSE m END)) OVER w) AS ibov,
       10000 * exp(sum(ln(1 + CASE WHEN k = 1 THEN 0 ELSE 1.1 * m + sx END)) OVER w) AS ifnc,
       20 * exp(sum(ln(1 + CASE WHEN k = 1 THEN 0 ELSE 0.9 * m + 0.5 * sx + e END)) OVER w) AS px
FROM rk_spine
WINDOW w AS (ORDER BY k);

INSERT INTO b3_index_level (index_code, trade_date, level)
SELECT 'IBOV', d, round(ibov::numeric, 6) FROM rk_levels
UNION ALL
SELECT 'IFNC', d, round(ifnc::numeric, 6) FROM rk_levels;

INSERT INTO b3_cotahist
    (codneg, trade_date, tpmerc, codbdi, especi, preco_fechamento, fator_cotacao, negocios, isin, raw)
SELECT 'RSKA3', d, '010', '02', 'ON NM', round(px::numeric, 6), 1, 5, 'BRRSKAACNOR1', '{}'::jsonb
FROM rk_levels WHERE k NOT IN (50, 51, 52)
UNION ALL
SELECT 'RSKF3', d, '010', '02', 'ON NM', 10, 1, 5, 'BRRSKFACNOR1', '{}'::jsonb
FROM rk_levels;

-- No events, proven swept: close_adj is the close. No cash history, so
-- close_total_return is NULL on every session and the stock leg is price_only.
INSERT INTO b3_corporate_event_sweep (issuing_company, n_events, proven_at)
VALUES ('RSKA', 0, '2025-01-10 06:00+00'), ('RSKF', 0, '2025-01-10 06:00+00');

-- A bank: CVM setor Bancos maps to IFNC.
INSERT INTO cia_company (cd_cvm, cnpj_cia, denom_cia, setor, raw)
VALUES ('99903', '11222333000343', 'RISK SA', 'Bancos', '{}');
INSERT INTO cia_ticker (cnpj_cia, data_refer, versao, codneg, raw)
VALUES ('11222333000343', '2024-01-01', 1, 'RSKA3', '{}');

REFRESH MATERIALIZED VIEW mv_b3_isin_subtype;
REFRESH MATERIALIZED VIEW mv_research_universe;

DO $$
DECLARE
    j      JSONB;
    f      JSONB;
    v_bm   DOUBLE PRECISION;
    v_n    INT;
    caught BOOLEAN;
BEGIN
    -- The whole sample, sector leg from the setor map.
    SELECT to_jsonb(x) INTO j FROM api.risk_decompose('rska3', '2024-01-02', '2024-12-31') x;
    f := j;
    ASSERT j->>'status' = 'ok', format('status: %s', j);
    ASSERT j->>'ticker' = 'RSKA3', format('ticker: %s', j->>'ticker');
    ASSERT j->>'sector_leg' = 'IFNC' AND j->>'sector_leg_basis' = 'cvm_setor_map',
        format('sector leg: %s %s', j->>'sector_leg', j->>'sector_leg_basis');
    ASSERT j->>'setor_current' = 'Bancos', format('setor: %s', j->>'setor_current');
    -- 197 stock sessions joined, 196 returns; 3 no-trade sessions inside.
    ASSERT (j->>'n_returns')::int = 196, format('n_returns: %s', j->>'n_returns');
    ASSERT (j->>'window_sessions')::int = 200, format('window_sessions: %s', j->>'window_sessions');
    ASSERT (j->>'no_trade_sessions')::int = 3, format('no_trade: %s', j->>'no_trade_sessions');
    ASSERT NOT (j->>'illiquid')::boolean, 'three of 200 sessions is not illiquid';
    -- No cash history: total return NULL everywhere, so price_only for the whole series.
    ASSERT j->>'stock_series' = 'price_only', format('series: %s', j->>'stock_series');
    ASSERT (j->>'null_sessions')::int = 197, format('null_sessions: %s', j->>'null_sessions');
    ASSERT j->'flags' ? 'price_only', format('flags: %s', j->'flags');
    -- The three shares add to 1.
    ASSERT abs((f->>'market_share')::numeric + (f->>'sector_share')::numeric
               + (f->>'residual_share')::numeric - 1) < 0.00001,
        format('shares do not add to 1: %s', f);
    -- beta_market is the OLS slope on IBOV, from returns of the JOINED levels.
    SELECT regr_slope(x.r, x.m), count(*) INTO v_bm, v_n
    FROM (SELECT c.preco_fechamento / lag(c.preco_fechamento) OVER w - 1 AS r,
                 i.level / lag(i.level) OVER w - 1 AS m
          FROM b3_cotahist c
          JOIN b3_index_level i ON i.index_code = 'IBOV' AND i.trade_date = c.trade_date
          WHERE c.codneg = 'RSKA3'
          WINDOW w AS (ORDER BY c.trade_date)) x
    WHERE x.r IS NOT NULL;
    ASSERT v_n = 196 AND abs((f->>'beta_market')::numeric - v_bm::numeric) < 0.000001,
        format('beta_market %s, OLS %s on %s returns', f->>'beta_market', v_bm, v_n);
    ASSERT abs((f->>'hedge_ibov')::numeric
               + ((f->>'beta_market')::numeric - (f->>'beta_sector')::numeric * (f->>'gamma')::numeric)) < 0.00001,
        format('hedge_ibov: %s', f);
    -- The shock session is found and the split is run again without it.
    ASSERT j->'shock_dates' ? (SELECT d::text FROM rk_spine WHERE k = 100),
        format('shock dates: %s', j->'shock_dates');
    ASSERT (j->>'ex_shock_n_returns')::int = 196 - jsonb_array_length(j->'shock_dates'),
        format('ex_shock n: %s', j->>'ex_shock_n_returns');

    -- p_sector none: two parts that add to 1.
    SELECT to_jsonb(x) INTO j FROM api.risk_decompose('RSKA3', '2024-01-02', '2024-12-31', 'none') x;
    f := j;
    ASSERT j->>'sector_leg' IS NULL AND j->>'sector_leg_basis' = 'caller', format('none: %s', j);
    ASSERT f->>'sector_share' IS NULL AND f->>'beta_sector' IS NULL, format('none full: %s', f);
    ASSERT abs((f->>'market_share')::numeric + (f->>'residual_share')::numeric - 1) < 0.00001,
        format('two parts do not add to 1: %s', f);

    -- A window before the first session starts at it, flagged.
    SELECT to_jsonb(x) INTO j FROM api.risk_decompose('RSKA3', '2023-06-01', '2024-12-31') x;
    ASSERT j->'flags' ? 'window_clamped', format('clamp: %s', j->'flags');
    ASSERT (j->>'n_returns')::int = 196, format('clamped n: %s', j->>'n_returns');

    -- Fewer than 120 returns: no split, counts still reported.
    SELECT to_jsonb(x) INTO j FROM api.risk_decompose('RSKA3', '2024-06-01', '2024-12-31') x;
    ASSERT j->>'status' = 'insufficient_sample' AND j->>'market_share' IS NULL,
        format('short window: %s', j);
    ASSERT (j->>'n_returns')::int BETWEEN 1 AND 119, format('short n: %s', j->>'n_returns');

    -- IBOV, an unknown code and an unknown ticker are refused with 22023.
    caught := FALSE;
    BEGIN
        PERFORM api.risk_decompose('RSKA3', '2024-01-02', '2024-12-31', 'IBOV');
    EXCEPTION WHEN SQLSTATE '22023' THEN caught := TRUE;
    END;
    ASSERT caught, 'p_sector IBOV must raise 22023';
    caught := FALSE;
    BEGIN
        PERFORM api.risk_decompose('RSKA3', '2024-01-02', '2024-12-31', 'ZZZZ');
    EXCEPTION WHEN SQLSTATE '22023' THEN caught := TRUE;
    END;
    ASSERT caught, 'an unknown index code must raise 22023';
    caught := FALSE;
    BEGIN
        PERFORM api.risk_decompose('NOPE3', '2024-01-02', '2024-12-31');
    EXCEPTION WHEN SQLSTATE '22023' THEN caught := TRUE;
    END;
    ASSERT caught, 'an unknown ticker must raise 22023';

    RAISE NOTICE 'risk_decompose behaviour: all checks passed';
END
$$;

-- The dashboard view: one row per IBOV member; a refused member keeps its
-- message and no split.
INSERT INTO b3_index_portfolio (reference_date, index_code, codneg, asset_name, participacao_pct, raw)
VALUES ('2024-12-30', 'IBOV', 'RSKA3', 'RISK', 1.5, '{}'),
       ('2024-12-30', 'IBOV', 'NOPE3', 'NOPE', 0.5, '{}'),
       ('2024-12-27', 'IBOV', 'OLDM3', 'OLD',  0.5, '{}');
REFRESH MATERIALIZED VIEW mv_risk_decompose_ibov;

DO $$
DECLARE
    r RECORD;
BEGIN
    ASSERT (SELECT count(*) FROM mv_risk_decompose_ibov) = 2, 'only the newest portfolio date';
    SELECT * INTO r FROM mv_risk_decompose_ibov WHERE ticker = 'RSKA3';
    ASSERT r.refusal IS NULL AND r.status = 'ok' AND r.sector_leg = 'IFNC'
           AND abs(r.market_share + r.sector_share + r.residual_share - 1) < 0.00001,
        format('RSKA3 row: %s', to_jsonb(r));
    SELECT * INTO r FROM mv_risk_decompose_ibov WHERE ticker = 'NOPE3';
    ASSERT r.refusal IS NOT NULL AND r.market_share IS NULL, format('NOPE3 row: %s', to_jsonb(r));
    RAISE NOTICE 'mv_risk_decompose_ibov behaviour: all checks passed';
END
$$;

ROLLBACK;
