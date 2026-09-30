-- Migration 56: the cash events behind the total-return close (#418), one
-- row per event, resolved once per refresh instead of once per request.
--
-- WHY A MATERIALIZED VIEW. vw_b3_cash_dividend_isin (migration 51) resolves the
-- ISIN of every distribution with a dated lateral join into the tape. Measured
-- on production 2026-09-30: 5.3 s over the 23,730 rows and 1.3 M buffer hits,
-- and the ISIN is computed inside the join, so a filter on one ISIN cannot be
-- pushed down. `anon` has statement_timeout = 3 s. The per-event work below
-- costs about 7 s once; api.quote_history reads the result by ISIN.
--
-- Like mv_b3_isin_subtype it is created WITH NO DATA here and refreshed by
-- 22_b3_tape_matviews.sql, where a failure fails the apply. It lives in a
-- migration and not in schema.sql because it reads a view that reads cia_ticker,
-- which only migration 25 creates. No client grant: the function reads it.
--
-- WHAT A ROW IS, by kind:
--   cash        a distribution whose ISIN is resolved AND whose published pre-ex
--               close agrees with the tape (close_match), with the tape's close
--               on the ex session. factor = 1 + value_per_share / ex_close: the
--               holder's return on the ex session is (P_ex + D) / P_cum, the
--               price return is P_ex / P_cum, so the level ratio between them is
--               1 + D / P_ex from then on. The ex session is the ISIN's first
--               printed session after last_date_prior_ex, and counts only within
--               7 calendar days: a paper that does not print within a week of
--               the entitlement date has no price to reinvest at (189 events
--               print 30+ days later, all in the research universe).
--   no_ex_close a resolved distribution with no such ex-session close, or no
--               readable amount. factor is NULL and so is every earlier level.
--   unresolved  a distribution whose ISIN is not resolved, or whose published
--               pre-ex close does not agree with the tape. It names the share
--               class B3 published (type_stock) and the ticker prefixes the
--               issuer has used (stems), so the function blocks only that
--               class of that issuer, never a guessed ISIN.
--   pending     a cash event in the last ~12 months that B3's supplement lists
--               (b3_corporate_event, ISIN included) and the full history does
--               not: the history lags, or has a hole. No age limit, because a
--               hole does not heal (FRAS, BRST: 3 measured, none from
--               September). It blocks that ISIN's earlier levels until the
--               history carries it.
--
-- WHICH ACTIONS. DIVIDENDO, JRS CAP PROPRIO (gross of withholding tax),
-- RENDIMENTO and REST CAP DIN, the same list for the history and for the
-- supplement check. CIS RED CAP (a reduction with no payment) and subscriptions
-- pay nothing and are not here; the price-adjusted close does not adjust them.

BEGIN;

-- IF NOT EXISTS: every schema apply replays the migrations, and a DROP here would
-- empty the view until the next analytical apply. A change to the definition is
-- a new migration.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_cash_event AS
WITH hist AS (
    SELECT v.*, v.value_cash_per_share AS per_share
    FROM vw_b3_cash_dividend_isin v
    WHERE v.last_date_prior_ex >= DATE '2019-01-02'
      AND v.corporate_action IN ('DIVIDENDO', 'JRS CAP PROPRIO', 'RENDIMENTO', 'REST CAP DIN')
),
resolved AS (
    SELECT h.* FROM hist h WHERE h.isin IS NOT NULL AND h.close_match IS TRUE
),
cash AS (
    SELECT
        'history'::text AS src, r.id AS src_id, r.isin, r.issuing_company, r.type_stock,
        r.corporate_action AS action, r.last_date_prior_ex AS event_date, r.per_share,
        x.ex_session, x.ex_close,
        CASE
            WHEN r.per_share IS NULL OR r.per_share <= 0 THEN 'no_ex_close'
            WHEN x.ex_close IS NULL OR x.ex_close <= 0   THEN 'no_ex_close'
            ELSE 'cash'
        END AS kind,
        CASE WHEN r.per_share > 0 AND x.ex_close > 0 THEN 1 + r.per_share / x.ex_close END AS factor,
        NULL::text[] AS stems
    FROM resolved r
    LEFT JOIN LATERAL (
        SELECT b.trade_date AS ex_session,
               b.preco_fechamento / NULLIF(b.fator_cotacao, 0) AS ex_close
        FROM public.b3_cotahist b
        WHERE b.tpmerc = '010' AND b.isin = r.isin AND b.codbdi = '02'
          AND b.trade_date > r.last_date_prior_ex
          AND b.trade_date <= r.last_date_prior_ex + 7
        ORDER BY b.trade_date
        LIMIT 1
    ) x ON TRUE
),
unresolved AS (
    SELECT
        'history'::text AS src, h.id AS src_id, NULL::text AS isin, h.issuing_company, h.type_stock,
        h.corporate_action AS action, h.last_date_prior_ex AS event_date, h.per_share,
        NULL::date AS ex_session, NULL::numeric AS ex_close,
        'unresolved'::text AS kind, NULL::numeric AS factor,
        ARRAY[h.issuing_company] || ARRAY(
            SELECT DISTINCT left(t.codneg, 4)
            FROM public.cia_ticker t
            WHERE h.cnpj IS NOT NULL AND t.cnpj_cia = h.cnpj AND length(t.codneg) >= 5
        ) AS stems
    FROM hist h
    WHERE NOT (h.isin IS NOT NULL AND h.close_match IS TRUE)
),
-- DISTINCT: a republished event can come back as a second row that differs only
-- in approved_on; it is still one event.
supp AS (
    SELECT DISTINCT ON (e.isin, e.label, e.last_date_prior, e.rate)
           e.id, e.isin, e.issuing_company, e.label, e.last_date_prior
    FROM public.b3_corporate_event e
    WHERE e.label IN ('DIVIDENDO', 'JRS CAP PROPRIO', 'RENDIMENTO', 'REST CAP DIN')
      AND e.last_date_prior >= DATE '2019-01-02'
      AND e.isin IS NOT NULL
    ORDER BY e.isin, e.label, e.last_date_prior, e.rate, e.id
),
pending AS (
    SELECT
        'supplement'::text AS src, s.id AS src_id, s.isin, s.issuing_company, NULL::text AS type_stock,
        s.label AS action, s.last_date_prior AS event_date, NULL::numeric AS per_share,
        NULL::date AS ex_session, NULL::numeric AS ex_close,
        'pending'::text AS kind, NULL::numeric AS factor, NULL::text[] AS stems
    FROM supp s
    WHERE NOT EXISTS (
            SELECT 1 FROM resolved r
            WHERE r.isin = s.isin AND r.last_date_prior_ex = s.last_date_prior
              AND r.corporate_action = s.label)
      -- An unresolved history row for the same issuer, date and action is
      -- already an 'unresolved' event; it is not also a missing one.
      AND NOT EXISTS (
            SELECT 1 FROM hist h
            WHERE h.isin IS NULL AND h.issuing_company = s.issuing_company
              AND h.last_date_prior_ex = s.last_date_prior
              AND h.corporate_action = s.label)
)
SELECT * FROM cash
UNION ALL SELECT * FROM unresolved
UNION ALL SELECT * FROM pending
WITH NO DATA;

-- One row per source row: also what lets the daily refresh run CONCURRENTLY.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_b3_cash_event ON mv_b3_cash_event (src, src_id);
CREATE INDEX IF NOT EXISTS idx_mv_b3_cash_event_isin ON mv_b3_cash_event (isin, event_date) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mv_b3_cash_event_unres ON mv_b3_cash_event USING gin (stems) WHERE kind = 'unresolved';

-- Supabase's default privileges hand every new public object SELECT for anon
-- and authenticated. Clients reach it only through api.quote_history.
REVOKE ALL ON mv_b3_cash_event FROM PUBLIC, anon, authenticated;

COMMENT ON MATERIALIZED VIEW mv_b3_cash_event IS
    'Internal (no client grant): one row per cash distribution since 2019-01-02 that api.quote_history folds into close_total_return, by kind: cash (resolved and tape-confirmed, with its ex-session factor), no_ex_close, unresolved (ISIN not proven; blocks that issuer''s share class) and pending (listed by B3''s supplement, absent from the full history). Refreshed by 22_b3_tape_matviews.sql.';

COMMIT;
