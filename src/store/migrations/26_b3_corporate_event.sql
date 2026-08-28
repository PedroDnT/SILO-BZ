-- Migration 26: published B3 corporate events (splits, groupings, bonuses,
-- cash dividends, subscriptions).
--
-- WHY: b3_cotahist is the tape as B3 published it — unadjusted. A split shows
-- up as a ~50% overnight move with no market behind it. The only honest fix is
-- an event table sourced from published corporate actions; inferring a factor
-- from the size of a price jump would fabricate the number the whole
-- adjustment rests on (CLAUDE.md rule 1), because a jump can equally be a
-- delisting-relisting, an illiquid re-print, or a real crash.
--
-- SOURCE: B3's listed-companies proxy (see
-- src/fetchers/b3_corporate_events_fetcher.py for the base64-path and
-- double-encoding quirks). Verified live 2026-08-28 — PETR carries
-- DESDOBRAMENTO rows from 2008, MGLU carries GRUPAMENTO and BONIFICACAO.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
-- --------------------------------------------
-- It does not derive an adjustment factor, and no view here rescales a price.
-- B3's `factor` is published per event label and its meaning is NOT uniform
-- across labels as far as this repository has verified: a PETR DESDOBRAMENTO
-- carries 100.0 while an MGLU GRUPAMENTO carries 0.1, which are consistent
-- with two different conventions (percentage distributed vs new-per-old
-- ratio). Picking one and applying it to every label would silently rescale
-- real prices by a wrong constant — worse than serving them unadjusted, which
-- at least is honest and documented.
--
-- So this migration lands the PUBLISHED FIELDS VERBATIM plus provenance. The
-- adjustment series ships only once the convention is confirmed per label
-- against the tape (the check: for each event, does close(last_date_prior) /
-- close(next session) match the candidate factor?). Until then `adjusted`
-- stays FALSE on every quote and the docs keep saying so.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_corporate_event (
    id                BIGSERIAL PRIMARY KEY,
    -- B3's 4-letter issuing company code (PETR, MGLU). Not the ticker: one
    -- issuer carries several tickers, and the events are per ISIN.
    issuing_company   TEXT        NOT NULL,
    -- The join key to b3_cotahist.isin. Published on every event row.
    isin              TEXT        NOT NULL,
    -- stock = changes the share count (adjustment-relevant)
    -- cash  = dividends / JCP (total-return relevant, not price-adjustment)
    -- subscription = rights offering
    event_class       TEXT        NOT NULL
        CHECK (event_class IN ('stock', 'cash', 'subscription')),
    -- B3's own label, upper-cased: DESDOBRAMENTO, GRUPAMENTO, BONIFICACAO,
    -- DIVIDENDO, JRS CAP PROPRIO, SUBSCRICAO. Stored as published — this
    -- table does not translate or bucket it.
    label             TEXT        NOT NULL,
    -- lastDatePrior: the LAST session on which the old entitlement still
    -- applied. The ex-date is the following TRADING session, which is a
    -- calendar question, so the derivation is left to the consumer and B3's
    -- own field is what gets stored.
    last_date_prior   DATE,
    approved_on       DATE,
    -- Published verbatim. See the header: the convention varies by label and
    -- is NOT interpreted here.
    factor            NUMERIC(28, 12),
    -- Cash events only: per-share amount.
    rate              NUMERIC(28, 12),
    payment_date      DATE,
    raw               JSONB       NOT NULL,
    source            TEXT        NOT NULL DEFAULT 'b3_listed_companies',
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency. An event is identified by what B3 publishes about it; NULLS NOT
-- DISTINCT so rows with a missing date or factor still collide instead of
-- duplicating on every re-fetch.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_corporate_event
    ON b3_corporate_event (isin, label, last_date_prior, approved_on, factor, rate)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_b3_corporate_event_isin_date
    ON b3_corporate_event (isin, last_date_prior DESC);

CREATE INDEX IF NOT EXISTS idx_b3_corporate_event_class
    ON b3_corporate_event (event_class, label);

COMMENT ON TABLE b3_corporate_event IS
    'Published B3 corporate actions per ISIN (splits, groupings, bonuses, cash dividends, subscriptions). Fields verbatim from B3''s listed-companies proxy. No adjustment factor is derived here: B3''s factor convention varies by label and is not yet verified against the tape, so quotes stay unadjusted and honest rather than rescaled by a guess.';

-- Events joined to the tape, so the factor convention can be CHECKED rather
-- than assumed: for each share-count event, what did the close actually do
-- across it? This view is the evidence for that verification and a research
-- surface in its own right; it applies no adjustment.
CREATE OR REPLACE VIEW vw_b3_share_count_event AS
SELECT
    e.issuing_company,
    e.isin,
    e.label,
    e.last_date_prior,
    e.approved_on,
    e.factor,
    -- The last cash print on or before the entitlement date, and the first one
    -- after it. Their ratio is what any candidate factor convention has to
    -- reproduce.
    (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
       FROM public.b3_cotahist b
      WHERE b.isin = e.isin AND b.tpmerc = '010'
        AND b.trade_date <= e.last_date_prior
      ORDER BY b.trade_date DESC, b.codbdi
      LIMIT 1)                                    AS close_unit_before,
    (SELECT b.preco_fechamento / NULLIF(b.fator_cotacao, 0)
       FROM public.b3_cotahist b
      WHERE b.isin = e.isin AND b.tpmerc = '010'
        AND b.trade_date > e.last_date_prior
      ORDER BY b.trade_date, b.codbdi
      LIMIT 1)                                    AS close_unit_after,
    e.raw
FROM b3_corporate_event e
WHERE e.event_class = 'stock';

COMMENT ON VIEW vw_b3_share_count_event IS
    'Share-count events (splits/groupings/bonuses) with the unit close on each side of the entitlement date. Evidence for verifying B3''s per-label factor convention against the tape before any adjusted price series is served. Applies no adjustment itself.';

COMMIT;
