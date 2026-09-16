-- =============================================================================
-- 21_lending_participants.sql
-- The read side of b3_lending_trade: who traded the borrow, per session.
--
-- Runs after 12 (grants), 19 (schema api) and 20 (short interest).
--
-- THE ONE THING THIS FILE REFUSES TO IMPLY
-- ----------------------------------------
-- `doador` and `tomador` are BROKERAGES. B3 names 33 participants in a whole
-- session, and on 2026-09-10 32,197 of 43,165 trades (74.6%) carried the same
-- code on both legs — a broker crossing its own clients. So a large borrow
-- through XP is XP's client book, not a position XP holds.
--
-- That is why `internal_trades` and `internal_qty` sit beside the totals
-- instead of being filtered out. Dropping the self-crossed trades would make
-- the remaining flow look like inter-broker conviction; keeping them silently
-- would make a broker's internal churn look like directional demand. Both are
-- misreadings, so the split is published and the caller chooses.
--
-- Plain views, not materialized: bounded by B3's ~21-business-day retention on
-- the source, so the fact is at most ~900k rows however long the pipeline runs.
-- =============================================================================

DROP VIEW IF EXISTS api.lending_trades              CASCADE;
DROP VIEW IF EXISTS api.lending_participants        CASCADE;
DROP VIEW IF EXISTS fact_lending_participant_daily  CASCADE;
DROP VIEW IF EXISTS fact_lending_trade_daily        CASCADE;

-- -----------------------------------------------------------------------------
-- fact_lending_trade_daily — the session's tape, per ticker.
-- -----------------------------------------------------------------------------
-- Overlaps b3_lending_rate on purpose: that table is B3's own published
-- average, this one is computed from the trades underneath it. Keeping both
-- means the published figure can be CHECKED rather than trusted, the same
-- stance vw_b3_share_count_event takes on corporate actions.
--
-- Measured on 2026-09-10 across the 569 tickers both cover: mean absolute
-- difference 0.037 percentage points, 561 of 569 within 0.5pp. The residual is
-- not error, it is METHOD — B3's glossary defines its average as weighted by
-- the NUMBER OF TRADES, while taxa_media_pct below weights by QUANTITY, so the
-- two diverge exactly where one broker does many small trades at a rate far
-- from the size-weighted middle (max observed gap 3.81pp). Neither is wrong;
-- they answer different questions, and this view does not overwrite B3's.
CREATE OR REPLACE VIEW fact_lending_trade_daily AS
SELECT
    t.trade_date,
    t.codneg,
    count(*)                                            AS trades,
    sum(t.quantidade)                                   AS quantidade,
    -- Quantity-weighted, which is the only average that means anything when
    -- trade sizes span six orders of magnitude in one session.
    sum(t.taxa_pct * t.quantidade)
        / NULLIF(sum(t.quantidade), 0)                  AS taxa_media_pct,
    min(t.taxa_pct)                                     AS taxa_min_pct,
    max(t.taxa_pct)                                     AS taxa_max_pct,
    count(DISTINCT t.tomador_codigo)                    AS tomadores,
    count(DISTINCT t.doador_codigo)                     AS doadores,
    count(*) FILTER (
        WHERE t.doador_codigo IS NOT DISTINCT FROM t.tomador_codigo
    )                                                   AS internal_trades,
    min(t.hora)                                         AS primeira_hora,
    max(t.hora)                                         AS ultima_hora
FROM public.b3_lending_trade t
GROUP BY t.trade_date, t.codneg;

COMMENT ON VIEW fact_lending_trade_daily IS
    'Per (session, ticker) aggregate of the individual lending trades: count, quantity, quantity-weighted and min/max annualized rate, distinct brokers on each leg, and how many trades a broker crossed internally. Computed from b3_lending_trade, so it can be checked against B3''s own published average in b3_lending_rate rather than replacing it.';

-- -----------------------------------------------------------------------------
-- fact_lending_participant_daily — what each brokerage did, per ticker.
-- -----------------------------------------------------------------------------
-- One row per (session, ticker, broker), with the lender and borrower legs
-- unioned and then summed, so a broker that appears on both sides of the same
-- ticker nets out naturally instead of being double-counted.
CREATE OR REPLACE VIEW fact_lending_participant_daily AS
WITH legs AS (
    SELECT
        t.trade_date, t.codneg,
        t.doador_codigo AS participant_code, t.doador_nome AS participant_name,
        t.quantidade    AS qty_lent,        0::numeric AS qty_borrowed,
        t.taxa_pct      AS rate_lent,       NULL::numeric AS rate_borrowed,
        (t.doador_codigo IS NOT DISTINCT FROM t.tomador_codigo) AS is_internal
    FROM public.b3_lending_trade t
    WHERE t.doador_codigo IS NOT NULL
    UNION ALL
    SELECT
        t.trade_date, t.codneg,
        t.tomador_codigo, t.tomador_nome,
        0::numeric,      t.quantidade,
        NULL::numeric,   t.taxa_pct,
        (t.doador_codigo IS NOT DISTINCT FROM t.tomador_codigo)
    FROM public.b3_lending_trade t
    WHERE t.tomador_codigo IS NOT NULL
)
SELECT
    l.trade_date,
    l.codneg,
    l.participant_code,
    -- B3 spells a participant's name consistently within a session; taking the
    -- max keeps the view deterministic if it ever does not.
    max(l.participant_name)                             AS participant_name,
    count(*)                                            AS legs,
    sum(l.qty_lent)                                     AS qty_lent,
    sum(l.qty_borrowed)                                 AS qty_borrowed,
    -- Positive = this broker's book lent more than it borrowed. A broker that
    -- crossed a trade internally contributes to BOTH sides, so it cancels here
    -- rather than inflating either direction.
    sum(l.qty_lent) - sum(l.qty_borrowed)               AS qty_net,
    sum(l.rate_lent * l.qty_lent)
        / NULLIF(sum(l.qty_lent) FILTER (WHERE l.rate_lent IS NOT NULL), 0)
                                                        AS taxa_doador_pct,
    sum(l.rate_borrowed * l.qty_borrowed)
        / NULLIF(sum(l.qty_borrowed) FILTER (WHERE l.rate_borrowed IS NOT NULL), 0)
                                                        AS taxa_tomador_pct,
    -- The honesty column. High internal share means this broker's flow is its
    -- own clients crossing, not a directional view taken against the market.
    count(*) FILTER (WHERE l.is_internal)               AS internal_legs,
    sum(l.qty_lent + l.qty_borrowed) FILTER (WHERE l.is_internal) AS internal_qty
FROM legs l
GROUP BY l.trade_date, l.codneg, l.participant_code;

COMMENT ON VIEW fact_lending_participant_daily IS
    'Per (session, ticker, brokerage): quantity lent, borrowed and net, with quantity-weighted rates on each leg. participant_code is a B3 BROKER, never a beneficial owner — internal_legs / internal_qty say how much of it is the broker crossing its own clients (about three quarters of all trades), which is the difference between client churn and a directional view.';

-- =============================================================================
-- Public read contract (schema api). Owner-privileged, same stance as 19/20.
-- =============================================================================

CREATE OR REPLACE VIEW api.lending_trades AS
SELECT
    d.trade_date,
    d.codneg           AS ticker,
    d.trades,
    d.quantidade       AS quantity,
    d.taxa_media_pct   AS rate_pct,
    d.taxa_min_pct     AS rate_min_pct,
    d.taxa_max_pct     AS rate_max_pct,
    d.tomadores        AS borrower_brokers,
    d.doadores         AS lender_brokers,
    d.internal_trades
FROM fact_lending_trade_daily d;

ALTER VIEW api.lending_trades SET (security_invoker = false);
GRANT SELECT ON api.lending_trades TO anon, authenticated;

COMMENT ON VIEW api.lending_trades IS
    'Daily securities-lending activity per ticker, computed from B3''s individual trades: count, quantity, quantity-weighted and min/max annualized rate (percentage points), and how many distinct brokers stood on each leg. History starts at first capture — B3 retains ~21 business days.';

CREATE OR REPLACE VIEW api.lending_participants AS
SELECT
    p.trade_date,
    p.codneg            AS ticker,
    p.participant_code  AS broker_code,
    p.participant_name  AS broker_name,
    p.qty_lent          AS quantity_lent,
    p.qty_borrowed      AS quantity_borrowed,
    p.qty_net           AS quantity_net,
    p.taxa_doador_pct   AS lender_rate_pct,
    p.taxa_tomador_pct  AS borrower_rate_pct,
    p.internal_legs,
    p.internal_qty
FROM fact_lending_participant_daily p;

ALTER VIEW api.lending_participants SET (security_invoker = false);
GRANT SELECT ON api.lending_participants TO anon, authenticated;

COMMENT ON VIEW api.lending_participants IS
    'Per (ticker, session, brokerage) securities-lending flow: quantity lent, borrowed and net, with rates. broker_* identifies the B3 PARTICIPANT intermediating, not the beneficial owner; internal_legs / internal_qty measure how much is that broker crossing its own clients. Do not read a large borrow as the broker being short.';

-- The landing table stays closed to client roles, like the rest of the group.
REVOKE ALL ON TABLE b3_lending_trade FROM anon, authenticated;

GRANT SELECT ON fact_lending_trade_daily       TO anon, authenticated;
GRANT SELECT ON fact_lending_participant_daily TO anon, authenticated;
