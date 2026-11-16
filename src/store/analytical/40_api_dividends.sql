-- =============================================================================
-- 40_api_dividends.sql
-- api.dividends(p_ticker, p_from, p_to): the cash distributions of one listed
-- ticker, as B3 publishes them (catalog v84, #1157). No new fetch: the rows are
-- already in b3_cash_dividend (migration 51) and b3_corporate_event (26, 72).
--
-- TWO B3 SOURCES, and `source` on the row says which one:
--   b3_cash_history  b3_cash_dividend: B3's full cash history (1995 on), per
--                    company and share class (typeStock), with the approval
--                    date, the last date with rights, the amount and B3's own
--                    pre-ex close and yield. It publishes NO payment date and
--                    no ISIN.
--   b3_supplement    b3_corporate_event (event_class = 'cash'): a window of
--                    about the last 12 months, per ISIN, WITH the payment
--                    date. SILO has kept it since 2025. A row here is served
--                    only when the history does not carry the event (yet):
--                    the history lags (recent declarations), and it does not
--                    cover every issuer (most FIIs pay only here).
--
-- WHICH ROWS. The ticker's share class is the first word of its ESPECI on its
-- newest cash print (PETR4 'PN N2' -> PN), the same rule that resolves the
-- history's ISIN in vw_b3_cash_dividend_isin. The company is every ticker
-- prefix of api.ticker_lineage plus the CNPJ that CVM's FCA map (cia_ticker)
-- publishes for those tickers, because B3 lists a renamed company under its
-- CURRENT code. So the history rows are the company's distributions for that
-- share class, not a guessed ISIN. The supplement rows are the lineage's ISINs.
--
-- DERIVED, AND HOW:
--   ex_date       the first B3 cash session (b3_cotahist, tpmerc 010) after
--                 last_date_with, within 10 days. The tape starts in 2019, so
--                 ex_date is NULL before that, and NULL until the session is on
--                 the tape. last_date_with is B3's own field: check it.
--   payment_date  history rows: the supplement's paymentDate for the same ISIN
--                 (of the lineage), action, last date with rights and amount
--                 (1e-8 tolerance). One distinct date serves every installment;
--                 when B3 lists n identical installments and the supplement has
--                 exactly n distinct dates, installment k takes the k-th date in
--                 order (the rows are identical, so the order assigns nothing
--                 else). Anything else is NULL, never a guess. Before 2025 it is
--                 NULL: B3 publishes no payment date in its history.
--   value_per_share  value_cash / quoted_per_shares (B3 quoted per 1000 shares
--                 in older records). JRS CAP PROPRIO is GROSS of withholding tax.
--
-- PRIVILEGES, ROW CAP: as 34. SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; EXECUTE revoked from PUBLIC,
-- granted to anon / authenticated and to silo_api. More than 1000 rows REFUSES
-- (22023 through api.assert_row_cap), never trimmed: narrow p_from / p_to.
--
-- Ordering: after 19 (api.assert_row_cap, api.ticker_lineage).
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL
       OR to_regprocedure('api.ticker_lineage(text)') IS NULL THEN
        RAISE EXCEPTION '40_api_dividends.sql needs api.assert_row_cap and api.ticker_lineage from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.b3_cash_dividend') IS NULL
       OR to_regclass('public.b3_corporate_event') IS NULL
       OR to_regclass('public.cia_ticker') IS NULL THEN
        RAISE EXCEPTION '40_api_dividends.sql serves b3_cash_dividend and b3_corporate_event; apply the schema and migrations first';
    END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION api.dividends(
    p_ticker TEXT,                  -- a B3 ticker (PETR4)
    p_from   DATE DEFAULT NULL,     -- first last_date_with; NULL = no lower bound
    p_to     DATE DEFAULT NULL      -- last last_date_with, inclusive; NULL = no upper bound
)
RETURNS TABLE (
    ticker          TEXT,     -- the ticker asked for
    isin            TEXT,     -- the supplement's ISIN when a supplement row matched; NULL otherwise
    company         TEXT,     -- B3 tradingName (history) or issuing company code (supplement)
    share_class     TEXT,     -- B3 typeStock: ON, PN, PNA, PNB, UNT ...
    action          TEXT,     -- DIVIDENDO, JRS CAP PROPRIO (gross of tax), RENDIMENTO ...
    approved_on     DATE,     -- B3 dateApproval / approvedOn
    last_date_with  DATE,     -- B3 lastDatePriorEx: the last session with the right
    ex_date         DATE,     -- the first B3 cash session after last_date_with (tape, 2019 on)
    payment_date    DATE,     -- B3 paymentDate (supplement, 2025 on); NULL when not published
    value_per_share NUMERIC,  -- BRL per share
    close_prior_ex  NUMERIC,  -- B3's pre-ex reference close per share (history rows)
    yield_pct       NUMERIC,  -- B3's corporateActionPrice: value / pre-ex close * 100 (history rows)
    installment     INT,      -- 1, 2, ... among byte-identical history rows (installments)
    source          TEXT      -- b3_cash_history | b3_supplement
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_t      TEXT := upper(btrim(COALESCE(p_ticker, '')));
    v_class  TEXT;
    v_isins  TEXT[];
    v_stems  TEXT[];
    v_cnpjs  TEXT[];
BEGIN
    IF v_t = '' THEN
        RAISE EXCEPTION 'dividends needs p_ticker: a B3 ticker such as PETR4 (find one with lookup)'
            USING ERRCODE = '22023';
    END IF;
    IF p_from IS NOT NULL AND p_to IS NOT NULL AND p_from > p_to THEN
        RAISE EXCEPTION 'dividends: p_from (%) is after p_to (%)', p_from, p_to
            USING ERRCODE = '22023';
    END IF;

    SELECT split_part(btrim(b.especi), ' ', 1) INTO v_class
    FROM public.b3_cotahist b
    WHERE b.codneg = v_t AND b.tpmerc = '010'
    ORDER BY b.trade_date DESC
    LIMIT 1;
    IF v_class IS NULL OR v_class = '' THEN
        RETURN;   -- a ticker with no cash print: no rows
    END IF;

    SELECT array_agg(DISTINCT l.isin), array_agg(DISTINCT left(l.ticker, 4))
      INTO v_isins, v_stems
      FROM api.ticker_lineage(v_t) l;
    v_isins := COALESCE(v_isins, '{}');
    v_stems := COALESCE(v_stems, ARRAY[left(v_t, 4)]);
    SELECT array_agg(DISTINCT t.cnpj_cia) INTO v_cnpjs
      FROM public.cia_ticker t
     WHERE left(t.codneg, 4) = ANY (v_stems) AND t.cnpj_cia IS NOT NULL;
    v_cnpjs := COALESCE(v_cnpjs, '{}');

    RETURN QUERY
    WITH hist AS (
        SELECT d.id, d.trading_name, d.type_stock, d.corporate_action,
               d.date_approval, d.last_date_prior_ex,
               d.value_cash / NULLIF(d.quoted_per_shares, 0)            AS per_share,
               d.closing_price_prior_ex / NULLIF(d.quoted_per_shares, 0) AS close_prior,
               d.corporate_action_price,
               d.occurrence::int AS occurrence,
               count(*) OVER (PARTITION BY d.trading_name, d.type_stock, d.corporate_action,
                                           d.last_date_prior_ex, d.date_approval, d.value_cash) AS n_inst
        FROM public.b3_cash_dividend d
        WHERE (d.issuing_company = ANY (v_stems) OR d.cnpj = ANY (v_cnpjs))
          AND d.type_stock = v_class
          AND (p_from IS NULL OR d.last_date_prior_ex >= p_from)
          AND (p_to   IS NULL OR d.last_date_prior_ex <= p_to)
    ),
    supp AS (
        SELECT DISTINCT ON (e.isin, e.label, e.last_date_prior, e.rate, e.payment_date)
               e.isin, e.issuing_company, e.label, e.approved_on, e.last_date_prior,
               e.rate, e.payment_date
        FROM public.b3_corporate_event e
        WHERE e.event_class = 'cash'
          AND e.isin = ANY (v_isins)
          AND (p_from IS NULL OR e.last_date_prior >= p_from)
          AND (p_to   IS NULL OR e.last_date_prior <= p_to)
        ORDER BY e.isin, e.label, e.last_date_prior, e.rate, e.payment_date, e.id
    ),
    -- Per history row: the supplement's distinct payment dates for its event.
    paid AS (
        SELECT h.id,
               min(s.isin) AS isin,
               array_agg(DISTINCT s.payment_date ORDER BY s.payment_date)
                   FILTER (WHERE s.payment_date IS NOT NULL) AS dates
        FROM hist h
        JOIN supp s
          ON s.label = h.corporate_action
         AND s.last_date_prior = h.last_date_prior_ex
         AND abs(s.rate - h.per_share) < 1e-8
        GROUP BY h.id
    ),
    rows_h AS (
        SELECT p.isin, h.trading_name AS company, h.type_stock, h.corporate_action,
               h.date_approval, h.last_date_prior_ex,
               CASE
                   WHEN cardinality(p.dates) = 1 THEN p.dates[1]
                   WHEN cardinality(p.dates) = h.n_inst THEN p.dates[h.occurrence]
               END AS payment_date,
               h.per_share, h.close_prior, h.corporate_action_price, h.occurrence,
               'b3_cash_history'::text AS src
        FROM hist h
        LEFT JOIN paid p ON p.id = h.id
    ),
    rows_s AS (
        SELECT s.isin, s.issuing_company AS company, v_class AS type_stock, s.label,
               s.approved_on, s.last_date_prior, s.payment_date, s.rate,
               NULL::numeric AS close_prior, NULL::numeric AS cap,
               (row_number() OVER (PARTITION BY s.isin, s.label, s.last_date_prior, s.rate
                                   ORDER BY s.payment_date))::int AS occurrence,
               'b3_supplement'::text AS src
        FROM supp s
        WHERE NOT EXISTS (
            SELECT 1 FROM hist h
            WHERE h.corporate_action = s.label
              AND h.last_date_prior_ex = s.last_date_prior
              AND abs(s.rate - h.per_share) < 1e-8)
    ),
    page AS (
        SELECT * FROM rows_h
        UNION ALL
        SELECT * FROM rows_s
        ORDER BY 6 DESC, 4, 7, 11
        LIMIT 1001
    )
    SELECT v_t, g.isin, g.company, g.type_stock, g.corporate_action,
           g.date_approval, g.last_date_prior_ex,
           (SELECT min(b.trade_date)
              FROM public.b3_cotahist b
             WHERE b.tpmerc = '010'
               AND b.trade_date >  g.last_date_prior_ex
               AND b.trade_date <= g.last_date_prior_ex + 10),
           g.payment_date, g.per_share, g.close_prior, g.corporate_action_price,
           g.occurrence, g.src
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'dividends')
    ORDER BY g.last_date_prior_ex DESC, g.corporate_action, g.payment_date NULLS LAST, g.occurrence
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.dividends(TEXT, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.dividends(TEXT, DATE, DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.dividends(TEXT, DATE, DATE) TO silo_api;

COMMENT ON FUNCTION api.dividends(TEXT, DATE, DATE) IS
    'Cash distributions (DIVIDENDO, JRS CAP PROPRIO gross of withholding tax, RENDIMENTO, ...) of one B3 ticker, newest last_date_with first. source b3_cash_history: B3''s full history (1995 on) for the company and the ticker''s share class (first word of ESPECI), with approval date, last date with rights, value per share, B3''s pre-ex close and yield; the company is matched by ticker prefix and the CNPJ CVM''s FCA map publishes, never by name. source b3_supplement: an event only B3''s ~12-month supplement lists (recent declarations, most FIIs). ex_date is the first B3 cash session after last_date_with on the tape (NULL before 2019 and until that session prints). payment_date is B3''s paymentDate from the supplement (2025 on), matched on ISIN, action, date and amount; NULL when B3 published none or the match is ambiguous, never guessed. installment numbers identical installment rows. p_from / p_to bound last_date_with (NULL = unbounded). A ticker with no cash print returns no rows. More than 1000 rows RAISES 22023 (never trimmed): narrow the window.';

COMMIT;
