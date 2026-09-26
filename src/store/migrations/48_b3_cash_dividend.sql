-- Migration 48: full published history of B3 cash distributions
-- (DIVIDENDO, JRS CAP PROPRIO, RENDIMENTO, ...), for total-return series.
--
-- WHY A SECOND TABLE: b3_corporate_event (migration 26) takes its cash rows
-- from GetListedSupplementCompany, whose cashDividends array is a rolling
-- window of roughly the last twelve months (verified 2026-09-26: PETR's oldest
-- supplement cash row is 2025, while its stockDividends reach back to 2008).
-- Before mid-2025 that table holds a few dozen cash rows per year for the
-- whole market, so any total return built on it silently equals the price
-- return. The companion endpoint GetListedCashDividends carries the whole
-- history (PETR: 343 rows back to 1996-03-21), paged.
--
-- WHY NO ISIN ON THE ROW: GetListedCashDividends publishes no ISIN. It is
-- keyed by the company's tradingName (the exact name, not a prefix: ITAU
-- returns nothing, ITAUSA and ITAUUNIBANCO are separate) and a share class
-- (typeStock: ON, PN, PNA, PNB, UNT ...). Building an ISIN from those parts
-- would synthesise a natural key (CLAUDE.md rule 3). So the row stores what
-- B3 published, and vw_b3_cash_dividend_isin resolves the ISIN by a DATED
-- join to the tape: the ISIN that printed under this issuer and class on the
-- session B3 names as the pre-ex close. The published pre-ex close is then
-- compared with the tape's close for that ISIN, so every resolution carries
-- its own evidence.
--
-- ORDERING QUIRK: B3 sorts this endpoint by typeStock and then by date
-- descending, so the first page of a multi-class issuer is often all ON.
-- "Only fetch page one" silently drops the PN history; the ingest pages to
-- the end every time and narrows what it upserts instead.

BEGIN;

CREATE TABLE IF NOT EXISTS b3_cash_dividend (
    id                          BIGSERIAL PRIMARY KEY,
    -- The 4-letter code we derived tradingName from (B3's GetInitialCompanies
    -- issuingCompany). Needed for the tape join; not a B3 field on this row.
    issuing_company             TEXT        NOT NULL,
    -- The exact tradingName the request was made with.
    trading_name                TEXT        NOT NULL,
    -- The company's CNPJ as B3's catalog (GetInitialCompanies) publishes it.
    -- B3 lists companies under their CURRENT code: Eletrobras is AXIA, and
    -- its ELET-era distributions come back under that name. The CNPJ joins
    -- to cia_ticker (CVM's published ticker history), which is how the view
    -- reaches ELET3/ELET6 for the pre-rename rows. NULL if B3 omits it.
    cnpj                        TEXT,
    -- typeStock verbatim: ON, PN, PNA, PNB, UNT ...
    type_stock                  TEXT        NOT NULL,
    -- corporateAction verbatim: DIVIDENDO, JRS CAP PROPRIO, RENDIMENTO ...
    corporate_action            TEXT        NOT NULL,
    date_approval               DATE,
    -- lastDatePriorEx: the last session with the entitlement. The ex-date is
    -- the next trading session; that derivation is left to the consumer.
    last_date_prior_ex          DATE,
    -- valueCash, per `quoted_per_shares` shares (1 today; 1000 on records
    -- from the era when B3 quoted per thousand shares).
    value_cash                  NUMERIC(28, 12),
    ratio                       NUMERIC(28, 12),
    quoted_per_shares           NUMERIC(28, 12),
    -- B3's own pre-ex reference close and the session it comes from.
    date_closing_price_prior_ex DATE,
    closing_price_prior_ex      NUMERIC(28, 12),
    -- corporateActionPrice: B3's published yield in percent
    -- (value_cash / closing_price_prior_ex * 100; PETR 1996: 5.1471/114.99).
    corporate_action_price      NUMERIC(28, 12),
    -- 1, 2, ... among rows B3 publishes byte-identically. Petrobras pays some
    -- distributions in equal installments and this endpoint (which carries no
    -- payment date) lists each as an identical row: PETR has 14 such pairs,
    -- e.g. two JRS CAP PROPRIO of 0.35048636 on 2026-06-01. Without this the
    -- unique key would collapse them and silently drop half the payout.
    -- Deterministic from the fetch (a count, not an order), so re-fetches
    -- land on the same keys.
    occurrence                  SMALLINT    NOT NULL DEFAULT 1,
    raw                         JSONB       NOT NULL,
    source                      TEXT        NOT NULL DEFAULT 'b3_listed_cash_dividends',
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency on what B3 publishes about the distribution. Two JCP rows on
-- the same date with different amounts stay distinct (PETR 2026-08-21 has
-- two); identical installments stay distinct through `occurrence`.
CREATE UNIQUE INDEX IF NOT EXISTS uq_b3_cash_dividend
    ON b3_cash_dividend (trading_name, type_stock, corporate_action,
                         last_date_prior_ex, date_approval, value_cash, occurrence)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_b3_cash_dividend_issuer_date
    ON b3_cash_dividend (issuing_company, type_stock, last_date_prior_ex DESC);

COMMENT ON TABLE b3_cash_dividend IS
    'Full published history of B3 cash distributions per company tradingName and share class (GetListedCashDividends), fields verbatim. No ISIN is published; vw_b3_cash_dividend_isin resolves it against the tape with evidence. Supersedes the ~12-month cash window in b3_corporate_event for total-return use.';

-- ISIN resolution with its evidence. For each distribution, the candidate
-- ISINs are those that printed on the standard lot board (codbdi 02) with
-- this share class ON the session B3 names as the pre-ex close, under any
-- ticker prefix the company is published to have used: its current B3 code
-- plus every prefix cia_ticker lists for its CNPJ (VVAR/VIIA/BHIA for Casas
-- Bahia). Exactly one candidate is a resolution; zero or several is
-- reported, never picked. close_match compares B3's published pre-ex close
-- with the tape close for the resolved ISIN on that same session.
CREATE OR REPLACE VIEW vw_b3_cash_dividend_isin AS
SELECT
    d.id,
    d.issuing_company,
    d.trading_name,
    d.cnpj,
    d.type_stock,
    d.corporate_action,
    d.date_approval,
    d.last_date_prior_ex,
    d.value_cash,
    d.quoted_per_shares,
    d.value_cash / NULLIF(d.quoted_per_shares, 0)      AS value_cash_per_share,
    d.date_closing_price_prior_ex,
    d.closing_price_prior_ex,
    c.n_isins,
    CASE WHEN c.n_isins = 1 THEN c.isins[1] END         AS isin,
    CASE WHEN c.n_isins = 1 THEN c.closes[1] END        AS tape_close_prior_ex,
    CASE WHEN c.n_isins = 1 AND d.closing_price_prior_ex > 0 THEN
        abs(c.closes[1] / (d.closing_price_prior_ex
                           / NULLIF(d.quoted_per_shares, 0)) - 1) < 0.005
    END                                                 AS close_match
FROM b3_cash_dividend d
LEFT JOIN LATERAL (
    SELECT count(*)::int                                AS n_isins,
           array_agg(q.isin ORDER BY q.isin)            AS isins,
           array_agg(q.close_unit ORDER BY q.isin)      AS closes
      FROM (
        SELECT DISTINCT ON (b.isin)
               b.isin,
               b.preco_fechamento / NULLIF(b.fator_cotacao, 0) AS close_unit
          FROM public.b3_cotahist b
         WHERE b.tpmerc = '010'
           AND b.codbdi = '02'
           AND b.isin IS NOT NULL
           -- B3's own pre-ex close session; when B3 leaves it blank (seen
           -- once in 1,344 sampled rows) its entitlement date is the session.
           AND b.trade_date = COALESCE(d.date_closing_price_prior_ex,
                                       d.last_date_prior_ex)
           AND left(b.codneg, 4) = ANY (
                   ARRAY[d.issuing_company]
                   || ARRAY(SELECT DISTINCT left(t.codneg, 4)
                              FROM public.cia_ticker t
                             WHERE d.cnpj IS NOT NULL
                               AND t.cnpj_cia = d.cnpj
                               AND length(t.codneg) >= 5))
           AND split_part(btrim(b.especi), ' ', 1) = d.type_stock
         ORDER BY b.isin, b.codneg
      ) q
) c ON TRUE;

COMMENT ON VIEW vw_b3_cash_dividend_isin IS
    'b3_cash_dividend with the ISIN resolved against the tape on B3''s own pre-ex close session (share class from ESPECI, under the current B3 code or any ticker prefix cia_ticker publishes for the company''s CNPJ). isin is NULL unless exactly one candidate printed; close_match says whether B3''s published pre-ex close agrees with the tape (0.5% tolerance). Resolution is evidence-backed, never guessed.';

COMMIT;
