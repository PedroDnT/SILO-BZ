-- =============================================================================
-- Migration 23 — B3 instrument typing: exercises/auctions relabeled,
--                fund-quota subtype, share class, governance segment
--
-- Everything here is derived ONLY from published COTAHIST fields (TPMERC,
-- CODBDI, ESPECI, ISIN). Nothing is inferred from ticker shape. All new
-- columns are TRAILING (CREATE OR REPLACE VIEW can only append columns), and
-- no existing instrument_type value that has consumers changes:
-- api.equities/bdrs/units/fund_quotas/cash_securities filter on the cash
-- labels, which are untouched.
--
-- 1. TPMERC 012/013 are option EXERCISES — events, not quotes. Migration 20
--    labeled them option_call/option_put, which contradicted the serve path
--    (api.option_chain/option_history filter tpmerc 070/080 only). Verified
--    no consumer reads the old labels (grep: only tests). Relabeled
--    option_exercise_call / option_exercise_put.
-- 2. TPMERC 017 is LEILÃO (auction) per B3's published market-type table —
--    measured 2026-08-27: 210 rows / 192 codnegs ≈ 1.05 rows per codneg,
--    i.e. auction prints, not a series. Was 'other'; now 'auction'.
-- 3. instrument_subtype splits fund_quota using B3's published CODBDI board
--    codes, the rule the rb3 project uses and validated against our own data
--    (2026-08-27, codnegs since 2026-08-01): codbdi 14 → etf (127 of 247
--    matched cvm_etf_registry tickers; spot sample ACWI11/AGRI11/B3BR11...),
--    codbdi 05/12 → fii (zero registry matches; sample ABCP11/ALZR3...),
--    codbdi 13 → fiagro. codbdi 14 + ESPECI 'FIDC%' would be a listed FIDC
--    (rb3's rule; zero rows today). Odd-lot boards (codbdi 93/96) carry no
--    family signal → NULL, never guessed.
-- 4. share_class parses the class token from ESPECI (fixed-width: class in
--    cols 1-4, rights flags in 5-8, listing segment in 9-10). Verified
--    against the ISIN class code (chars 10-11) on the whole 2026-08 cash
--    tape: ON↔OR, PN↔PR, PNA↔PA, PNB↔PB, PNC↔PC — zero disagreements.
--    Unrecognized token → NULL.
-- 5. governance_segment is the trailing listing-segment code (NM/N1/N2/MA/
--    M2/MB), previously jammed inside ESPECI where callers had to substring
--    it themselves.
--
-- tpmerc 021 stays classified with the cash/odd-lot family: it is absent
-- from B3's published TPMERC table, but measured rows (2026-08) carry
-- codbdi 93 and 'Q'-suffixed codnegs (VBBR3Q, BOVA11Q) alongside tpmerc 020
-- fractional prints. Documented assumption, revisit if B3 publishes the code.
-- =============================================================================

CREATE OR REPLACE VIEW vw_b3_instrument_typed AS
SELECT
    q.*,
    CASE
        WHEN q.tpmerc = '070' THEN 'option_call'
        WHEN q.tpmerc = '080' THEN 'option_put'
        WHEN q.tpmerc = '012' THEN 'option_exercise_call'
        WHEN q.tpmerc = '013' THEN 'option_exercise_put'
        WHEN q.tpmerc = '017' THEN 'auction'
        WHEN q.tpmerc = '030' THEN 'forward'
        WHEN q.tpmerc IN ('010', '020', '021') THEN
            CASE
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DR%'  THEN 'bdr'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'UNT%' THEN 'unit'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%' THEN 'fund_quota'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
                  OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%'  THEN 'equity'
                ELSE 'cash_security'
            END
        ELSE 'other'
    END AS instrument_type,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%') THEN
            CASE
                WHEN q.codbdi IN ('05', '12') THEN 'fii'
                WHEN q.codbdi = '13' THEN 'fiagro'
                WHEN q.codbdi = '14' THEN
                    CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                         THEN 'fidc' ELSE 'etf' END
                ELSE NULL
            END
        ELSE NULL
    END AS instrument_subtype,
    CASE
        WHEN split_part(btrim(COALESCE(q.especi, '')), ' ', 1)
             IN ('ON', 'PN', 'PNA', 'PNB', 'PNC', 'PND', 'UNT')
        THEN split_part(btrim(q.especi), ' ', 1)
        ELSE NULL
    END AS share_class,
    CASE
        WHEN btrim(substr(COALESCE(q.especi, ''), 9, 2))
             IN ('NM', 'N1', 'N2', 'MA', 'M2', 'MB')
        THEN btrim(substr(q.especi, 9, 2))
        ELSE NULL
    END AS governance_segment
FROM b3_cotahist q;

COMMENT ON VIEW vw_b3_instrument_typed IS
    'COTAHIST rows classified from published TPMERC/CODBDI/ESPECI only. tpmerc 012/013 are option exercise EVENTS (not quotes); 017 is an auction print. fund_quota is split into etf/fii/fidc/fiagro via instrument_subtype using CODBDI board codes (validated vs cvm_etf_registry); NULL when the board carries no family signal. Grain and natural key unchanged.';
COMMENT ON COLUMN vw_b3_instrument_typed.instrument_type IS
    'option_call | option_put | option_exercise_call | option_exercise_put | auction | forward | bdr | unit | fund_quota | equity | cash_security | other';
COMMENT ON COLUMN vw_b3_instrument_typed.instrument_subtype IS
    'fund_quota family from CODBDI: etf (14) | fii (05/12) | fiagro (13) | fidc (14 + ESPECI FIDC*). NULL for non-fund rows and for boards with no family signal (odd lot 93/96). Never guessed from ticker shape.';
COMMENT ON COLUMN vw_b3_instrument_typed.share_class IS
    'Share class token from ESPECI: ON | PN | PNA | PNB | PNC | PND | UNT. Cross-checked against the ISIN class code (chars 10-11: OR/PR/PA/PB/PC) with zero disagreements on the 2026-08 cash tape. NULL when ESPECI carries no recognized class.';
COMMENT ON COLUMN vw_b3_instrument_typed.governance_segment IS
    'B3 listing segment from ESPECI cols 9-10: NM (Novo Mercado) | N1 | N2 | MA | M2 | MB. NULL when absent.';
