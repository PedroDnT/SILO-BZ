-- Migration 27: vw_b3_instrument_typed v3 — index lines, rights and bonuses get
-- their own types, and an ETF stays an ETF when B3 changes its board code.
--
-- Everything here is driven by what the tape actually contains, measured in
-- production on 2026-08-28 (health.yml diagnostics mode). No token is
-- reclassified on a hunch.
--
-- FINDING 1 — the cash_security bucket was a junk drawer.
-- Its top members by volume are DIR% (direitos de subscrição), BNS% (bonus
-- rights), CPA and TPR: claims and rights, not securities anyone would call
-- "cash securities". The docs said the bucket was "exchange-traded debt
-- (debentures, CRI/CRA)", which the data does not support. The residual ELSE
-- had simply swallowed every ESPECI the CASE did not name.
--
-- FINDING 2 — IBOV11 is not an ETF, and it is not a cash security either.
--   codneg IBOV11 | codbdi 02 | especi 'IBO' / 'IBO/' | isin BRIBOVINDM18
-- The ISIN's instrument segment is IND — an INDEX line, the Ibovespa itself
-- printed on the tape. It fell into cash_security because no CASE arm named it.
-- Note the trap: a "tickers ending in 11 are ETFs or UNITs" rule would have
-- labelled this index an ETF, which is why the rule here is ESPECI + ISIN, both
-- published, and never the ticker's shape.
--
-- FINDING 3 — B3 moved ETFs between board codes, and the subtype rule broke.
-- BOVA11, BOVV11 and IVVB11 each printed under codbdi 14 for their whole
-- history EXCEPT 2019-08-19 → 2019-12-30 (92 sessions), where they printed
-- under codbdi 02 with the same ESPECI and the same ISIN. Since
-- instrument_subtype was derived from codbdi alone, those sessions returned
-- NULL, and the dashboard's ETF volume chart — which filters
-- instrument_subtype = 'etf' — showed ZERO ETF volume for 2019-09 through
-- 2019-12 while the underlying prints sat in the table all along.
--
-- The fix is identity, not guesswork: an ISIN identifies one instrument. If an
-- ISIN prints as an ETF under a board code that says so on any session, it is
-- the same ETF on every session. mv_b3_isin_subtype carries that mapping,
-- derived only from rows the board code classifies unambiguously, and the view
-- falls back to it when the row's own board code is silent. An ISIN that never
-- prints under a classifying board code stays NULL — still never guessed.

BEGIN;

-- Per-ISIN subtype, learned from the sessions where CODBDI is decisive.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_b3_isin_subtype AS
SELECT
    t.isin,
    -- Modal subtype: an ISIN whose board codes disagree across its history
    -- takes the one it printed under most often, and ties break
    -- deterministically by name so the view is stable between refreshes.
    (ARRAY_AGG(t.subtype ORDER BY t.n DESC, t.subtype))[1] AS subtype,
    SUM(t.n)                                               AS classified_sessions
FROM (
    SELECT
        q.isin,
        CASE
            WHEN q.codbdi IN ('05', '12') THEN 'fii'
            WHEN q.codbdi = '13'          THEN 'fiagro'
            WHEN q.codbdi = '14'          THEN
                CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                     THEN 'fidc' ELSE 'etf' END
        END        AS subtype,
        COUNT(*)   AS n
    FROM public.b3_cotahist q
    WHERE q.tpmerc IN ('010', '020', '021')
      AND q.isin IS NOT NULL
      AND q.codbdi IN ('05', '12', '13', '14')
      AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
        OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%')
    GROUP BY 1, 2
) t
WHERE t.subtype IS NOT NULL
GROUP BY t.isin;

-- UNIQUE so the LEFT JOIN below cannot multiply rows of the tape, and so the
-- refresh can run CONCURRENTLY without blocking readers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_isin_subtype ON mv_b3_isin_subtype (isin);

COMMENT ON MATERIALIZED VIEW mv_b3_isin_subtype IS
    'ISIN -> fund subtype (etf/fii/fiagro/fidc), learned only from sessions whose CODBDI is decisive. Lets an instrument keep its identity across sessions where B3 printed it under a different board code (measured: BOVA11/BOVV11/IVVB11 under codbdi 02 from 2019-08-19 to 2019-12-30).';

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
                -- New in v3, each from a published ESPECI prefix that was
                -- previously falling into the residual bucket.
                -- 'index' also requires the ISIN's IND instrument segment, so a
                -- ticker merely starting with IBO cannot become an index.
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'IBO%'
                 AND COALESCE(q.isin, '') LIKE 'BR____IND%'   THEN 'index'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'DIR%' THEN 'right'
                WHEN UPPER(COALESCE(q.especi, '')) LIKE 'BNS%' THEN 'bonus'
                -- Residual, and now genuinely residual: whatever ESPECI B3
                -- prints that none of the above names.
                ELSE 'cash_security'
            END
        ELSE 'other'
    END AS instrument_type,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'CI%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%') THEN
            COALESCE(
                CASE
                    WHEN q.codbdi IN ('05', '12') THEN 'fii'
                    WHEN q.codbdi = '13' THEN 'fiagro'
                    WHEN q.codbdi = '14' THEN
                        CASE WHEN UPPER(COALESCE(q.especi, '')) LIKE 'FIDC%'
                             THEN 'fidc' ELSE 'etf' END
                    ELSE NULL
                END,
                -- Same ISIN, same instrument: recover the subtype from the
                -- sessions where the board code was decisive.
                m.subtype
            )
        ELSE NULL
    END AS instrument_subtype,
    CASE
        WHEN q.tpmerc IN ('010', '020', '021')
         AND (UPPER(COALESCE(q.especi, '')) LIKE 'ON%'
           OR UPPER(COALESCE(q.especi, '')) LIKE 'PN%')
         AND SPLIT_PART(BTRIM(COALESCE(q.especi, '')), ' ', 1)
             IN ('ON', 'PN', 'PNA', 'PNB', 'PNC', 'PND', 'UNT')
        THEN SPLIT_PART(BTRIM(COALESCE(q.especi, '')), ' ', 1)
        ELSE NULL
    END AS share_class,
    CASE
        WHEN BTRIM(COALESCE(SUBSTR(q.especi, 9, 2), '')) IN ('NM','N1','N2','MA','M2','MB')
        THEN BTRIM(SUBSTR(q.especi, 9, 2))
        ELSE NULL
    END AS governance_segment
FROM public.b3_cotahist q
LEFT JOIN mv_b3_isin_subtype m ON m.isin = q.isin;

COMMENT ON VIEW vw_b3_instrument_typed IS
    'B3 COTAHIST rows classified from PUBLISHED fields only (TPMERC, ESPECI, CODBDI, ISIN). v3: index/right/bonus split out of the residual cash_security bucket, and fund subtype falls back to the ISIN''s own classified sessions so an ETF stays an ETF across a board-code change.';

COMMIT;
