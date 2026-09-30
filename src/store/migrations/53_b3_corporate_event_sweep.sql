-- Migration 53: per-issuer proof that the corporate-event sweep covered it
-- (#413), so a price-adjusted close is served only where the events behind
-- it are known to be complete.
--
-- WHY PROOF IS PER ISSUER: GetListedSupplementCompany is one request per
-- issuing code and returns that company's WHOLE published stock-event history
-- (stored rows reach back to 1979; #372). A code whose supplement came back is
-- therefore complete for the tape's span. A code that was never asked for
-- (the old 400-day sweep left out about 115 of the 452 equity/unit prefixes),
-- that B3's catalog does not list (ADMF3 trades as B100 S.A.), or whose
-- request failed has no proof, and its adjusted close stays NULL with a reason
-- instead of silently equal to the raw close.
--
-- A row is written only for a code whose supplement came back and whose
-- events were upserted in the same run. Nothing else writes it, so the table
-- never claims a sweep that did not happen. A later failure does not erase an
-- earlier proof: the events it proved are still in b3_corporate_event.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_corporate_event_sweep (
    -- The 4-letter issuing code the sweep asked B3 for (PETR, MGLU): the
    -- ticker's first four characters, as _traded_issuers derives it.
    issuing_company TEXT        NOT NULL,
    -- Events B3 returned for the code on that run, all classes. 0 is B3
    -- saying "none", which is a proof too.
    n_events        INT         NOT NULL,
    -- When the supplement last came back and its events were stored.
    proven_at       TIMESTAMPTZ NOT NULL,
    -- cvm_ingest_log.run_id of that sweep.
    run_id          TEXT,
    CONSTRAINT uq_b3_corporate_event_sweep UNIQUE (issuing_company)
);

COMMENT ON TABLE b3_corporate_event_sweep IS
    'One row per B3 issuing code whose listed-company supplement (its full published corporate-event history) came back and was stored by the corporate-event sweep; proven_at is the latest such run. A code with no row is unproven, and api.quote_history serves its price-adjusted close as NULL with a reason.';

COMMIT;
