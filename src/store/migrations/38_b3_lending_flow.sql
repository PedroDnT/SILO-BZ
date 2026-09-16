-- 38_b3_lending_flow.sql — securities lending, investor flow, free float, instruments.
--
-- Adds the six landing tables behind the Short Monitor and the B3 half of the
-- flow dashboard. Every statement is idempotent (IF NOT EXISTS + named UNIQUE
-- constraints), and the same DDL is mirrored into schema.sql, which stays
-- canonical. Authored to be psql-clean: CI applies with -v ON_ERROR_STOP=1.

-- ---------------------------------------------------------------------------
-- B3 securities lending (BTC/BTB) and investor-type participation.
--
-- WHY THESE TABLES EXIST AS A RATCHET
-- -----------------------------------
-- B3 publishes all of this free, with no auth, through the BDI export API
-- (see src/fetchers/b3_bdi_fetcher.py for the verified contract) — but it
-- retains only a ~21-BUSINESS-DAY ROLLING WINDOW. Verified 2026-09-16:
-- 2026-08-17 returns data, 2026-08-14 returns "Nenhum resultado", and a
-- request spanning 2024-01-02..2026-09-10 comes back HTTP 200 with 5.2 MB
-- containing exactly 18 sessions. There is no archive: the legacy
-- requestname API still serves >1 year but knows none of these tables, and
-- the pesquisapregao bulletin archive returns empty zips.
--
-- So unlike every CVM table in this schema, a gap here is PERMANENT. A missed
-- cron run is not "re-run the backfill", it is a hole in the series forever.
-- That is why run_backfill offers no lending option and why
-- scripts/check_staleness.py must escalate a gap in these tables harder than
-- a gap in a CVM one.
-- ---------------------------------------------------------------------------

-- Open short interest per ticker. Source table: BTBLendingOpenPosition.
--
-- THE 'Total' TRAP. For every (date, ticker, tipo) B3 publishes the per-market
-- rows AND a Mercado = 'Total' row that is exactly their sum — 1036 of 1036
-- groups on 2026-09-10 carried one. SUM(saldo_brl) over this table is
-- therefore 2x the real short balance. Every published row is kept (integrity
-- rule 3: we do not drop what the source published), and `is_total` marks
-- B3's own aggregate so a consumer cannot double-count by accident. Read the
-- is_total rows, or the others, never both.
CREATE TABLE IF NOT EXISTS b3_lending_open_position (
    id                BIGSERIAL PRIMARY KEY,
    trade_date        DATE         NOT NULL,
    -- "Código IF" — the B3 ticker (PETR4). Joins b3_cotahist.codneg.
    codneg            TEXT         NOT NULL,
    isin              TEXT,
    empresa           TEXT,
    -- "Tipo de empréstimo" is B3's specification code for the security
    -- (ON, ON NM, PN N2, DRE, CI ...), not a kind of loan. Part of the key
    -- because one ticker can carry more than one.
    tipo_emprestimo   TEXT         NOT NULL,
    -- Registro | Neg. Eletrônica D+0 | Neg. Eletrônica D+1 | ETF Renda Fixa | Total
    mercado           TEXT         NOT NULL,
    is_total          BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Shares on loan and their market value. NUMERIC(28,4) rather than an
    -- integer: B3 publishes integers today, and a scale of 0 would silently
    -- ROUND a fractional quantity if that ever changed.
    saldo_quantidade  NUMERIC(28, 4),
    preco_medio       NUMERIC(20, 6),
    saldo_brl         NUMERIC(28, 2),
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw               JSONB        NOT NULL,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_open_position
        UNIQUE (trade_date, codneg, tipo_emprestimo, mercado)
);

CREATE INDEX IF NOT EXISTS idx_b3_lending_open_position_codneg
    ON b3_lending_open_position (codneg, trade_date DESC);
-- The analytical layer only ever reads B3's own aggregate, and it reads it
-- one session at a time.
CREATE INDEX IF NOT EXISTS idx_b3_lending_open_position_total
    ON b3_lending_open_position (trade_date DESC, codneg)
    WHERE is_total;

COMMENT ON TABLE b3_lending_open_position IS
    'Open securities-lending positions per ticker (B3 BTBLendingOpenPosition), i.e. the short balance. B3 retains ~21 business days, so this table can only ever be as deep as the daily job has been running — there is no backfill. Mercado = ''Total'' rows are B3''s own sum of the other markets: filter on is_total or you will double-count.';

-- Lending rates per ticker. Source table: BTBLoanBalance.
--
-- Rates are annualized percentage points as published (0.15 = 0,15% a.a.),
-- the same convention as anbima_class_monthly.rentabilidade_pct. The doador
-- (lender) and tomador (borrower) trios are distinguished by the export's
-- band row, never by column order — see src/parsers/b3_bdi.py.
CREATE TABLE IF NOT EXISTS b3_lending_rate (
    id                 BIGSERIAL    PRIMARY KEY,
    trade_date         DATE         NOT NULL,
    codneg             TEXT         NOT NULL,
    isin               TEXT,
    empresa            TEXT,
    mercado            TEXT         NOT NULL,
    num_contratos      INTEGER,
    quantidade         NUMERIC(28, 4),
    valor_brl          NUMERIC(28, 2),
    taxa_doador_min    NUMERIC(12, 4),
    taxa_doador_media  NUMERIC(12, 4),
    taxa_doador_max    NUMERIC(12, 4),
    taxa_tomador_min   NUMERIC(12, 4),
    taxa_tomador_media NUMERIC(12, 4),
    taxa_tomador_max   NUMERIC(12, 4),
    source             TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw                JSONB        NOT NULL,
    fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_lending_rate UNIQUE (trade_date, codneg, mercado)
);

CREATE INDEX IF NOT EXISTS idx_b3_lending_rate_codneg
    ON b3_lending_rate (codneg, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_lending_rate_date
    ON b3_lending_rate (trade_date DESC);

COMMENT ON TABLE b3_lending_rate IS
    'Registered securities-lending contracts and their annualized rates per ticker (B3 BTBLoanBalance). taxa_* are percentage points as published; media is B3''s trade-count-weighted average for the session. Same ~21-business-day retention as b3_lending_open_position.';

-- Daily investor-type participation. Source table: SharesInvesVolum.
--
-- MONTH-TO-DATE, T+2. Each export is cumulative from the first of the month
-- to the caption date, and the caption runs two sessions behind the request
-- (a 2026-09-10 request is captioned 08/09/2026). reference_date is the
-- CAPTION date — keying on the request date would file two different
-- snapshots on one day and manufacture a flow out of nothing.
--
-- Daily net flow is therefore a DERIVED first difference of consecutive
-- snapshots within a month (fact_investor_flow_daily), not a stored column.
--
-- Values are R$ thousands exactly as B3 publishes them; the column name says
-- so rather than rescaling into a unit the source never used.
CREATE TABLE IF NOT EXISTS b3_investor_participation (
    id                       BIGSERIAL    PRIMARY KEY,
    reference_date           DATE         NOT NULL,
    -- Institucionais | Instituições Financeiras | Investidor Estrangeiro |
    -- Investidores Individuais | Outros — B3's labels, stored as published.
    investor_type            TEXT         NOT NULL,
    compras_brl_mil          NUMERIC(28, 2),
    compras_participacao_pct NUMERIC(12, 4),
    vendas_brl_mil           NUMERIC(28, 2),
    vendas_participacao_pct  NUMERIC(12, 4),
    source                   TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw                      JSONB        NOT NULL,
    fetched_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_investor_participation UNIQUE (reference_date, investor_type)
);

CREATE INDEX IF NOT EXISTS idx_b3_investor_participation_date
    ON b3_investor_participation (reference_date DESC);

COMMENT ON TABLE b3_investor_participation IS
    'Month-to-date buy/sell volume by investor type (B3 SharesInvesVolum), R$ thousands as published, dated by the export''s own "até o dia" caption (B3 publishes with a T+2 lag). Cumulative within a month and resets on the 1st — take first differences via fact_investor_flow_daily, never subtract across a month boundary.';

-- Previous-month investor participation by market. Source: SharesInvesVolumMonthly.
-- Only the latest month is ever available (past dates return "Nenhum
-- resultado"), so this table is also forward-only.
CREATE TABLE IF NOT EXISTS b3_investor_participation_monthly (
    id                BIGSERIAL    PRIMARY KEY,
    reference_month   DATE         NOT NULL,   -- first day of the month
    investor_type     TEXT         NOT NULL,
    -- À vista | A termo | Opções | Exercícios de opções | Blocos | Total geral
    market            TEXT         NOT NULL,
    valor_brl         NUMERIC(28, 2),
    participacao_pct  NUMERIC(12, 4),
    source            TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw               JSONB        NOT NULL,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_investor_participation_monthly
        UNIQUE (reference_month, investor_type, market)
);

COMMENT ON TABLE b3_investor_participation_monthly IS
    'Previous-month buy+sell volume by investor type and market segment (B3 SharesInvesVolumMonthly), R$ as published. Only the most recent month is retrievable, so history accrues one month per run.';

-- Index constituents with B3's free-float-adjusted share count and sector.
-- Source: sistemaswebb3-listados indexProxy GetPortfolioDay.
--
-- theoricalQty is the FREE FLOAT (the index's float-adjusted share count),
-- not shares outstanding — which is why dim_ticker_float prefers it and
-- records float_basis when it has to fall back.
CREATE TABLE IF NOT EXISTS b3_index_portfolio (
    id               BIGSERIAL    PRIMARY KEY,
    reference_date   DATE         NOT NULL,
    index_code       TEXT         NOT NULL,     -- IBOV, IBRA, SMLL, IBXX
    codneg           TEXT         NOT NULL,
    asset_name       TEXT,
    especificacao    TEXT,
    -- B3's own sector label ("Bens Indls / Mat Transporte"), returned only
    -- when the request asks for segment "2".
    b3_sector        TEXT,
    participacao_pct NUMERIC(12, 6),
    theoretical_qty  NUMERIC(28, 4),
    source           TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw              JSONB        NOT NULL,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_index_portfolio UNIQUE (reference_date, index_code, codneg)
);

CREATE INDEX IF NOT EXISTS idx_b3_index_portfolio_codneg
    ON b3_index_portfolio (codneg, reference_date DESC);

COMMENT ON TABLE b3_index_portfolio IS
    'B3 index theoretical portfolios: free-float-adjusted share count (theoretical_qty) and B3 sector per constituent. The only free, B3-published free float available; covers index members only (IBOV 76, IBRA ~148), which is why dim_ticker_float falls back to shares outstanding for the tail and labels which basis it used.';

-- Cash-market instrument registry. Source: InstrumentsEquities, filtered to
-- Mercado = 'EQUITY-CASH' (the raw export is ~110k rows/day, ~95% of them
-- option series that have no business here).
--
-- capital_social is the share count for that instrument class — the
-- denominator dim_ticker_float uses when a ticker is in no B3 index.
CREATE TABLE IF NOT EXISTS b3_instrument_registry (
    id               BIGSERIAL    PRIMARY KEY,
    reference_date   DATE         NOT NULL,
    instrumento      TEXT         NOT NULL,     -- the ticker (PETR4)
    ativo            TEXT,                      -- the issuer stem (PETR)
    descricao        TEXT,
    segmento         TEXT,
    mercado          TEXT,
    categoria        TEXT,                      -- SHARES | UNIT | BDR | ETF ...
    isin             TEXT,
    nome_instituicao TEXT,
    capital_social   NUMERIC(28, 4),
    nivel_governanca TEXT,                      -- NIVEL 1 | NIVEL 2 | NOVO MERCADO ...
    source           TEXT         NOT NULL DEFAULT 'b3_bdi',
    raw              JSONB        NOT NULL,
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_b3_instrument_registry UNIQUE (reference_date, instrumento)
);

CREATE INDEX IF NOT EXISTS idx_b3_instrument_registry_instrumento
    ON b3_instrument_registry (instrumento, reference_date DESC);
CREATE INDEX IF NOT EXISTS idx_b3_instrument_registry_isin
    ON b3_instrument_registry (isin, reference_date DESC);

COMMENT ON TABLE b3_instrument_registry IS
    'B3 cash-market instrument registry (InstrumentsEquities, Mercado = EQUITY-CASH): ISIN, category, governance level and capital_social (shares outstanding for that class). Sourced daily; the option series in the raw export are not stored.';
