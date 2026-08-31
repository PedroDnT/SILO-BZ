-- 36_b3_isin_date_index.sql — make the ISIN-keyed price lookup an index scan.
--
-- WHAT WAS SLOW. vw_b3_share_count_event answers, per corporate event, "what was
-- the last cash close on or before the entitlement date, and the first one
-- after". Both are:
--
--     WHERE isin = ? AND tpmerc = '010' AND trade_date <= ?
--     ORDER BY trade_date DESC LIMIT 1
--
-- The only index that applied was idx_b3_cotahist_isin (isin) — unordered — so
-- each lookup fetched EVERY row that ISIN ever printed (twenty years for a
-- liquid name) and sorted them to take one. At 1,382 events that is 2,764 such
-- scans, and the diagnostic that verifies B3's factor convention exceeded its
-- 90-second budget and was skipped on every health run. The blocker on serving
-- an adjusted close was therefore partly self-inflicted: not missing data, an
-- unanswerable query.
--
-- idx_b3_cotahist_vista is keyed on (codneg, trade_date) and carries isin only
-- as an INCLUDE payload, so it cannot drive an isin-keyed search either.
--
-- WHY THIS SHAPE. (isin, trade_date DESC) with the same tpmerc = '010' partial
-- predicate as idx_b3_cotahist_vista: options are ~89% of every session and have
-- no business in this plan. Each lookup becomes a one-row index scan from either
-- direction — Postgres reads a DESC index backwards for the ORDER BY trade_date
-- ASC side at the same cost.
--
-- This is not diagnostic-only scaffolding. Computing close_adj at all means
-- walking each instrument's events against its own tape by ISIN, which is this
-- exact access pattern.
--
-- Not CONCURRENTLY: every other index in this schema is built plainly, the
-- schema gate is serialized ahead of ingest by the supabase-ingest concurrency
-- group, and CONCURRENTLY cannot run inside the transaction the apply path uses.

CREATE INDEX IF NOT EXISTS idx_b3_cotahist_isin_dt
    ON b3_cotahist (isin, trade_date DESC)
    INCLUDE (preco_fechamento, fator_cotacao)
    WHERE tpmerc = '010' AND isin IS NOT NULL;

COMMENT ON INDEX idx_b3_cotahist_isin_dt IS
    'Drives the ISIN-keyed price lookup in vw_b3_share_count_event and any event-sourced adjustment: last close on or before a date, first after it. INCLUDEs both columns those callers read so the lookup stays index-only.';
