-- =============================================================================
-- Migration 20 — conservative B3 instrument typing
--
-- Keep COTAHIST at its published register-01 grain. Types are a read-side
-- classification derived only from B3's TPMERC and ESPECI fields; both source
-- values remain visible. In particular, ESPECI='CI' does not distinguish an
-- ETF quota from an FII quota, so it is deliberately just `fund_quota`.
-- =============================================================================

-- REPLAY GUARD (2026-08-27): migration 23 widens this view with trailing
-- columns (instrument_subtype, share_class, governance_segment). Migrations
-- replay on every apply, and CREATE OR REPLACE VIEW cannot drop columns, so
-- replaying this file against the widened view fails the whole bootstrap
-- ("cannot drop columns from view"). The original DDL below is preserved
-- verbatim and now runs only when the view does not exist yet (a database
-- restored from before this migration); everywhere else schema.sql has
-- already created the current shape and this file is a no-op.
DO $mig20$
BEGIN
  IF EXISTS (
    SELECT FROM information_schema.views
    WHERE table_schema = 'public' AND table_name = 'vw_b3_instrument_typed'
  ) THEN
    RETURN;
  END IF;

  CREATE OR REPLACE VIEW vw_b3_instrument_typed AS
  SELECT
      q.*,
      CASE
          WHEN q.tpmerc IN ('012', '070') THEN 'option_call'
          WHEN q.tpmerc IN ('013', '080') THEN 'option_put'
          WHEN q.tpmerc = '030' THEN 'forward'
          WHEN q.tpmerc IN ('010', '020', '021') THEN
              CASE
                  WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DR%'  THEN 'bdr'
                  WHEN UPPER(COALESCE(q.especi, '')) LIKE 'UNT%' THEN 'unit'
                  WHEN UPPER(COALESCE(q.especi, '')) LIKE 'CI%'  THEN 'fund_quota'
                  WHEN UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
                    OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%'  THEN 'equity'
                  ELSE 'cash_security'
              END
          ELSE 'other'
      END AS instrument_type
  FROM b3_cotahist q;

  COMMENT ON VIEW vw_b3_instrument_typed IS
      'COTAHIST rows classified from published TPMERC/ESPECI only. fund_quota intentionally does not guess ETF versus FII. Grain and natural key are unchanged.';
  COMMENT ON COLUMN vw_b3_instrument_typed.instrument_type IS
      'option_call | option_put | forward | bdr | unit | fund_quota | equity | cash_security | other';
END
$mig20$;
