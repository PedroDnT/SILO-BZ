-- =============================================================================
-- Migration 72 - b3_corporate_event keeps every published row (#353, part of
--                #347)
--
-- WHY. uq_b3_corporate_event was (isin, label, last_date_prior, approved_on,
-- factor, rate), and pg_client dedups "last write wins" before the upsert, so
-- rows B3 publishes that agree on those six fields replaced each other.
-- Measured on 2026-10-05 against GetListedSupplementCompany for all 3,534
-- issuing codes in B3's listed-companies catalog (no request failed): 3,977
-- events, 3,769 keys under the old index, 204 distinct rows lost. The groups:
--
--   * cash paid in installments, rows differing only in paymentDate:
--     JRS CAP PROPRIO (38 groups), DIVIDENDO (27);
--   * one stock event delivering two assets, rows differing in assetIssued:
--     CIS RED CAP (32), INCORPORACAO (1);
--   * subscriptions of two assets (assetIssued, and percentage or priceUnit):
--     SUBSCRICAO (25), PRIORIDADE SUBS (3), SUBS C/ RENUNC (2).
--
-- No DESDOBRAMENTO, GRUPAMENTO or BONIFICACAO collided, so the price-adjusted
-- close was not affected on that date. Adding payment_date and asset_issued to
-- the key loses no distinct row; what remains are byte-identical duplicates.
--
-- WHAT.
--   1. asset_issued TEXT: B3's assetIssued, the asset the event delivers, as
--      published and upper-cased like the ISIN. Filled for the stored rows from
--      their own raw JSON (every stored row carries assetIssued; checked
--      2026-10-05), so a re-fetch matches the row it already wrote.
--   2. uq_b3_corporate_event (same name) widens to
--      (isin, label, last_date_prior, approved_on, factor, rate, payment_date,
--       asset_issued), NULLS NOT DISTINCT. Guarded on the live definition so the
--      replay on every schema apply is a no-op. A wider key never conflicts with
--      rows that were unique on a narrower one.
--
-- The readers that count share-count events (api.close_adj_status, api.panel)
-- refuse one label on one date paid in two assets instead of counting it once
-- (19_api_contract.sql). The cash readers only test whether an event exists,
-- so installments change nothing there.
--
-- Lost rows come back as each issuer is swept again: the nightly corporate-event
-- step covers a rotating slice of the traded issuers.
-- =============================================================================

ALTER TABLE b3_corporate_event ADD COLUMN IF NOT EXISTS asset_issued TEXT;

UPDATE b3_corporate_event
SET asset_issued = NULLIF(upper(btrim(raw ->> 'assetIssued')), '')
WHERE asset_issued IS NULL
  AND NULLIF(upper(btrim(raw ->> 'assetIssued')), '') IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = 'uq_b3_corporate_event'
          AND indexdef LIKE '%asset_issued%'
    ) THEN
        DROP INDEX IF EXISTS uq_b3_corporate_event;
        CREATE UNIQUE INDEX uq_b3_corporate_event
            ON b3_corporate_event (isin, label, last_date_prior, approved_on, factor, rate,
                                   payment_date, asset_issued)
            NULLS NOT DISTINCT;
    END IF;
END $$;

COMMENT ON COLUMN b3_corporate_event.asset_issued IS
    'B3''s assetIssued: the asset the event delivers, as published (upper-cased). A stock dividend, a reduction or a subscription can deliver another class than the ISIN it is published on, or two assets at once; each is its own row (migration 72, #353).';
