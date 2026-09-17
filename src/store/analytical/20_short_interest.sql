-- =============================================================================
-- 20_short_interest.sql
-- The read side of the B3 securities-lending and investor-flow tables:
-- short interest (% of float, days to cover, lending rates), the sector
-- aggregate, and daily investor net flow.
--
-- Runs after 12 (grants/roles) and 19 (schema api), so both exist here and the
-- api views at the foot of this file can be granted immediately.
--
-- TWO NUMBERS THIS FILE REFUSES TO INVENT
-- ---------------------------------------
-- 1. `pct_float` needs a float. B3 publishes a real free float only for index
--    constituents (b3_index_portfolio.theoretical_qty, ~149 tickers). For
--    everything else the honest denominator is shares outstanding
--    (b3_instrument_registry.capital_social), which is a LARGER number and so
--    yields a SMALLER percentage than the free-float figure the market quotes.
--    Those are not the same metric, so `float_basis` says which one produced
--    every row and no consumer has to guess.
-- 2. `days_to_cover` needs an ADTV. When a ticker has not traded in the
--    window, or the trailing average quantity is zero, the ratio is NULL —
--    never 0, never "high". A short position in an untraded name is
--    uncoverable, not instantly coverable, and 0 would sort it to exactly the
--    wrong end of the screen.
--
-- Everything here is a plain view, not a materialized one. B3 keeps ~21
-- business days of lending data, so the whole fact is bounded at roughly
-- 60k rows no matter how long the pipeline runs — small enough that freshness
-- beats a refresh schedule that could silently go stale.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Recreate from scratch, innermost last.
-- -----------------------------------------------------------------------------
-- CREATE OR REPLACE VIEW cannot insert a column in the middle of an existing
-- view's column list, and these views gain columns as the panels grow. A
-- guarded DROP makes the apply idempotent across versions instead of failing
-- on "cannot change name of view column" the first time a column lands before
-- an existing one.
--
-- CASCADE is confined to this file's own dependents (the api.* views below are
-- the only things that read these), so it cannot repeat 18_savings_flow's
-- lesson about a CASCADE reaching a relation nothing here owns.
DROP VIEW IF EXISTS api.short_interest           CASCADE;
DROP VIEW IF EXISTS api.short_interest_by_sector CASCADE;
DROP VIEW IF EXISTS api.investor_flow            CASCADE;
DROP VIEW IF EXISTS vw_short_by_sector           CASCADE;
DROP VIEW IF EXISTS fact_short_interest_daily    CASCADE;
DROP VIEW IF EXISTS fact_investor_flow_daily     CASCADE;
DROP VIEW IF EXISTS dim_ticker_float             CASCADE;
DROP VIEW IF EXISTS vw_b3_adtv_21                CASCADE;

-- -----------------------------------------------------------------------------
-- Trailing 21-session ADTV, per ticker per session.
-- -----------------------------------------------------------------------------
-- The window is computed per short-interest date rather than once over "the
-- latest 21 sessions", so a row dated three weeks ago is divided by the volume
-- that actually preceded IT.
--
-- `adtv_sessions` is exposed on purpose: early in a listing, or after a long
-- halt, the average is over fewer than 21 sessions. That is a usable estimate
-- but a noisier one, and the consumer is told rather than left to assume.
CREATE OR REPLACE VIEW vw_b3_adtv_21 AS
WITH recent AS (
    SELECT
        q.codneg,
        q.trade_date,
        q.volume,
        q.quantidade
    FROM public.vw_b3_quote_vista q
    -- Bounded so this never walks the whole tape: the lending tables cannot
    -- reach further back than B3's retention anyway, and 180 days is a wide
    -- margin around the 21 sessions the window needs. Partition pruning on
    -- b3_cotahist (RANGE by trade_date) does the rest.
    WHERE q.trade_date >= (SELECT max(b.trade_date) FROM public.b3_cotahist b) - 180
)
SELECT
    codneg,
    trade_date,
    avg(volume)     OVER w AS adtv_brl_21,
    avg(quantidade) OVER w AS adtv_qty_21,
    count(*)        OVER w AS adtv_sessions
FROM recent
WINDOW w AS (
    PARTITION BY codneg
    ORDER BY trade_date
    ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
);

COMMENT ON VIEW vw_b3_adtv_21 IS
    'Trailing 21-session average traded value and quantity per (ticker, session), from the cash tape. adtv_sessions says how many sessions the average actually covers — fewer than 21 means a shorter, noisier window, not a gap.';

-- -----------------------------------------------------------------------------
-- dim_ticker_float — one row per ticker: the float denominator and its basis.
-- -----------------------------------------------------------------------------
-- WHY AN INDEX PRIORITY RATHER THAN "the newest row". A ticker in more than
-- one index has more than one theoretical_qty, because the indices cap
-- constituent weights differently. Verified 2026-09-16: PETR3 is
-- 3,478,479,815 in IBRA but 2,441,951,100 in IBOV, and VALE3 is 4,262,140,818
-- against 3,687,404,862. A cap can only SHRINK the quantity below the real
-- float, so the broad, least-capped index is the closest published estimate —
-- IBRA first, then SMLL, then IBOV. `float_source_index` records which
-- portfolio the number came from, so the choice is auditable rather than
-- buried in this comment.
CREATE OR REPLACE VIEW dim_ticker_float AS
WITH latest_index AS (
    SELECT DISTINCT ON (p.codneg)
        p.codneg,
        p.theoretical_qty,
        p.index_code,
        p.b3_sector,
        p.asset_name,
        p.reference_date
    FROM public.b3_index_portfolio p
    WHERE p.theoretical_qty IS NOT NULL
      AND p.theoretical_qty > 0
    ORDER BY
        p.codneg,
        p.reference_date DESC,
        CASE p.index_code WHEN 'IBRA' THEN 1 WHEN 'SMLL' THEN 2 WHEN 'IBXX' THEN 3
                          WHEN 'IBOV' THEN 4 ELSE 5 END
),
latest_instrument AS (
    SELECT DISTINCT ON (r.instrumento)
        r.instrumento AS codneg,
        r.capital_social,
        r.isin,
        r.categoria,
        r.nivel_governanca,
        r.nome_instituicao,
        r.reference_date
    FROM public.b3_instrument_registry r
    ORDER BY r.instrumento, r.reference_date DESC
),
-- WHY THESE TWO ARE COLLAPSED BEFORE THEY ARE JOINED. Neither source is keyed
-- the way a naive join assumes, and joining them raw fans this view out — it
-- stops being one row per ticker, and every short position downstream is
-- counted once per duplicate.
--
--   * vw_company_ticker is DISTINCT ON (cnpj_cia, codneg) — one row per
--     (company, ticker), NOT per ticker. A ticker CVM published under two
--     CNPJs (a re-registration, a holding and its predecessor) yields two.
--   * cia_company's primary key is cd_cvm, not cnpj_cia. One CNPJ carrying
--     two CVM registration codes yields two more, multiplicatively.
--
-- Observed in production 2026-09-16: ITUB3 rendered twice in /short's
-- days-to-cover table with identical figures, and its R$3.05bn position was
-- summed twice into the headline short book. Both picks below are recorded
-- rather than arbitrary: the live listing and the ATIVO registration win,
-- then the newest filing, then the identifier itself so the choice is stable
-- across runs instead of depending on scan order.
company_ticker AS (
    SELECT DISTINCT ON (ct.codneg)
        ct.codneg,
        ct.cnpj_cia
    FROM public.vw_company_ticker ct
    WHERE ct.cnpj_cia IS NOT NULL
    ORDER BY ct.codneg, ct.is_active DESC, ct.data_refer DESC, ct.versao DESC,
             ct.cnpj_cia
),
company AS (
    -- COALESCE, not a bare DESC: `situacao = 'ATIVO'` is NULL when situacao is,
    -- and Postgres sorts NULLs FIRST under DESC — which would prefer a company
    -- with no published situacao over the active one.
    SELECT DISTINCT ON (c.cnpj_cia)
        c.cnpj_cia,
        c.denom_cia,
        c.setor
    FROM public.cia_company c
    WHERE c.cnpj_cia IS NOT NULL
    ORDER BY c.cnpj_cia, COALESCE(c.situacao = 'ATIVO', false) DESC, c.cd_cvm
)
SELECT
    COALESCE(i.codneg, x.codneg)                       AS codneg,
    COALESCE(i.nome_instituicao, x.asset_name)         AS asset_name,
    i.isin,
    i.categoria,
    i.nivel_governanca,
    x.b3_sector,
    -- B3 publishes 'Setor / Subsetor' in one string ('Financ e Outros /
    -- Interms Financs'), which is ~34 buckets — too granular to read as a
    -- sector chart. The part before the slash is B3's own top-level sector,
    -- so this splits rather than invents a taxonomy.
    --
    -- The index feed then spells the SAME sector several ways: 'Bens Indls'
    -- and 'Bens Industriais', 'Financ e Outros' and 'Financeiro e Outros',
    -- 'Cons N Cíclico' / 'Cons N Ciclico' / 'Cons N  Básico' (verified
    -- 2026-09-16 across IBOV/IBRA/SMLL). Left alone, one sector draws two or
    -- three bars. The CASE below merges SPELLINGS ONLY — every branch maps a
    -- variant onto the same sector B3 already assigned it to, and no ticker
    -- is moved between sectors. A prefix this list does not recognise
    -- (including the slash-less ones B3 publishes, such as
    -- 'Petróleo, Gás e Biocombustíveis' or 'Comput e Equips') passes through
    -- verbatim rather than being guessed into a parent, because promoting a
    -- subsector to a sector on a hunch is exactly the invented taxonomy this
    -- comment is here to avoid.
    CASE lower(regexp_replace(btrim(split_part(x.b3_sector, '/', 1)), '\s+', ' ', 'g'))
        WHEN 'bens indls'       THEN 'Bens Industriais'
        WHEN 'bens industriais' THEN 'Bens Industriais'
        WHEN 'financ e outros'      THEN 'Financeiro e Outros'
        WHEN 'financeiro e outros'  THEN 'Financeiro e Outros'
        WHEN 'cons n cíclico' THEN 'Consumo não Cíclico'
        WHEN 'cons n ciclico' THEN 'Consumo não Cíclico'
        WHEN 'cons n básico'  THEN 'Consumo não Cíclico'
        WHEN 'cons n basico'  THEN 'Consumo não Cíclico'
        WHEN 'consumo cíclico' THEN 'Consumo Cíclico'
        WHEN 'consumo ciclico' THEN 'Consumo Cíclico'
        WHEN 'mats básicos'    THEN 'Materiais Básicos'
        WHEN 'mats basicos'    THEN 'Materiais Básicos'
        WHEN 'utilidade públ'  THEN 'Utilidade Pública'
        WHEN 'utilidade publ'  THEN 'Utilidade Pública'
        ELSE NULLIF(regexp_replace(btrim(split_part(x.b3_sector, '/', 1)), '\s+', ' ', 'g'), '')
    END                                                AS b3_sector_top,
    x.theoretical_qty                                  AS free_float_shares,
    i.capital_social                                   AS shares_outstanding,
    -- The denominator actually used, and the label that keeps the two
    -- metrics from being read as one.
    COALESCE(x.theoretical_qty, i.capital_social)      AS float_denominator,
    CASE
        WHEN x.theoretical_qty IS NOT NULL THEN 'index_free_float'
        WHEN i.capital_social  IS NOT NULL THEN 'shares_outstanding'
        ELSE NULL
    END                                                AS float_basis,
    x.index_code                                       AS float_source_index,
    -- The company behind the ticker, when CVM published the pair. Never
    -- matched on name: vw_company_ticker takes both identifiers from the
    -- same FCA row.
    ct.cnpj_cia,
    co.denom_cia,
    co.setor                                           AS cvm_setor,
    GREATEST(COALESCE(x.reference_date, '0001-01-01'::date),
             COALESCE(i.reference_date, '0001-01-01'::date)) AS as_of
FROM latest_instrument i
FULL OUTER JOIN latest_index x   ON x.codneg = i.codneg
LEFT  JOIN company_ticker ct     ON ct.codneg = COALESCE(i.codneg, x.codneg)
LEFT  JOIN company co            ON co.cnpj_cia = ct.cnpj_cia;

COMMENT ON VIEW dim_ticker_float IS
    'Per-ticker float denominator with its provenance: free_float_shares from the broadest B3 index portfolio that carries the ticker (IBRA > SMLL > IBXX > IBOV, because index weight caps only shrink the figure), shares_outstanding from the cash-market instrument registry, and float_basis naming which one float_denominator used. The two are different metrics — % of free float is always larger than % of shares outstanding for the same position.';

-- -----------------------------------------------------------------------------
-- fact_short_interest_daily — the Short Monitor's spine.
-- -----------------------------------------------------------------------------
-- Reads ONLY the is_total rows. B3 publishes, per (session, ticker, spec),
-- both the per-market breakdown and its own 'Total' sum; adding them together
-- doubles every short balance. See migration 39.
CREATE OR REPLACE VIEW fact_short_interest_daily AS
WITH position AS (
    SELECT
        p.trade_date,
        p.codneg,
        p.isin,
        p.empresa,
        sum(p.saldo_quantidade) AS short_qty,
        sum(p.saldo_brl)        AS short_brl,
        -- One ticker can carry several specs (ON / ON NM). They are summed,
        -- and the specs are kept so the row can be traced back.
        string_agg(DISTINCT p.tipo_emprestimo, ', ' ORDER BY p.tipo_emprestimo) AS especificacoes
    FROM public.b3_lending_open_position p
    WHERE p.is_total
    GROUP BY p.trade_date, p.codneg, p.isin, p.empresa
),
rate AS (
    -- Rates are published per market. The volume-weighted mean across markets
    -- is the session's rate for the ticker; markets with no registered
    -- quantity carry a nominal rate on zero business and are excluded so they
    -- cannot drag the average.
    SELECT
        r.trade_date,
        r.codneg,
        sum(r.quantidade)                                      AS rate_quantidade,
        sum(r.num_contratos)                                   AS num_contratos,
        sum(r.valor_brl)                                       AS rate_valor_brl,
        sum(r.taxa_doador_media  * r.quantidade)
            / NULLIF(sum(r.quantidade), 0)                     AS taxa_doador_pct,
        sum(r.taxa_tomador_media * r.quantidade)
            / NULLIF(sum(r.quantidade), 0)                     AS taxa_tomador_pct,
        max(r.taxa_tomador_max)                                AS taxa_tomador_max_pct
    FROM public.b3_lending_rate r
    WHERE r.quantidade IS NOT NULL AND r.quantidade > 0
    GROUP BY r.trade_date, r.codneg
)
SELECT
    p.trade_date,
    p.codneg,
    p.isin,
    COALESCE(f.asset_name, p.empresa)     AS asset_name,
    p.especificacoes,
    f.b3_sector,
    f.b3_sector_top,
    -- SHARES / UNIT / BDR / ETF EQUITIES / FUNDS, from the instrument
    -- registry. Exposed because an unfiltered days-to-cover screen is
    -- dominated by index ETFs (PIBB11, BOVA11): they are legitimately on
    -- loan against tiny secondary volume, but they are not the crowded
    -- single-name shorts the screen is for. Filtering belongs to the
    -- consumer, so the column is published rather than the rows dropped.
    f.categoria,
    f.cnpj_cia,
    p.short_qty,
    p.short_brl,
    f.float_denominator,
    f.float_basis,
    f.float_source_index,
    -- Percentage points. NULL, not 0, when there is no denominator: an
    -- unknown float is unknown, and 0% would read as "nobody is short".
    CASE
        WHEN f.float_denominator IS NULL OR f.float_denominator <= 0 THEN NULL
        ELSE 100.0 * p.short_qty / f.float_denominator
    END                                   AS pct_float,
    a.adtv_qty_21,
    a.adtv_brl_21,
    a.adtv_sessions,
    -- Short Interest Ratio: sessions of average volume needed to buy the
    -- position back. NULL when the name did not trade — see the header.
    CASE
        WHEN a.adtv_qty_21 IS NULL OR a.adtv_qty_21 <= 0 THEN NULL
        ELSE p.short_qty / a.adtv_qty_21
    END                                   AS days_to_cover,
    r.taxa_doador_pct,
    r.taxa_tomador_pct,
    r.taxa_tomador_max_pct,
    r.num_contratos,
    r.rate_valor_brl
FROM position p
LEFT JOIN dim_ticker_float f ON f.codneg = p.codneg
LEFT JOIN vw_b3_adtv_21    a ON a.codneg = p.codneg AND a.trade_date = p.trade_date
LEFT JOIN rate             r ON r.codneg = p.codneg AND r.trade_date = p.trade_date;

COMMENT ON VIEW fact_short_interest_daily IS
    'Short interest per (session, ticker): balance on loan, % of float with the basis that produced it, days to cover against trailing 21-session ADTV, and quantity-weighted lending rates. Built from B3''s own Total rows only, so balances are not double-counted. pct_float and days_to_cover are NULL when their denominator is missing — never defaulted to zero.';

-- -----------------------------------------------------------------------------
-- vw_short_by_sector — the sector bar on the Short Monitor.
-- -----------------------------------------------------------------------------
-- Sector comes from the B3 index portfolios, so it covers the index universe;
-- everything else aggregates under 'Não classificado' rather than being
-- silently dropped, because a sector chart that quietly omits a third of the
-- short book is worse than one that shows the gap.
CREATE OR REPLACE VIEW vw_short_by_sector AS
SELECT
    s.trade_date,
    COALESCE(s.b3_sector_top, 'Não classificado') AS b3_sector,
    count(*)                                      AS tickers,
    sum(s.short_brl)                              AS short_brl,
    sum(s.short_qty)                              AS short_qty,
    -- Equities only, for the chart that means to show single-name risk:
    -- the unclassified bucket is almost entirely ETFs and BDRs, which B3
    -- assigns no sector and which would otherwise dominate the bar.
    sum(s.short_brl) FILTER (WHERE s.categoria IN ('SHARES', 'UNIT')) AS short_brl_equities
FROM fact_short_interest_daily s
GROUP BY s.trade_date, COALESCE(s.b3_sector_top, 'Não classificado');

COMMENT ON VIEW vw_short_by_sector IS
    'Short balance by B3 top-level sector per session (the part of Setor / Subsetor before the slash). Tickers B3 publishes no sector for — ETFs, BDRs, and anything outside the index portfolios — are bucketed as Não classificado rather than dropped; short_brl_equities restricts to SHARES and UNIT for the single-name view.';

-- -----------------------------------------------------------------------------
-- fact_investor_flow_daily — net flow by investor type, per session.
-- -----------------------------------------------------------------------------
-- b3_investor_participation is MONTH-TO-DATE cumulative, so a day's flow is
-- the first difference of consecutive snapshots WITHIN a month. Two ways that
-- goes wrong, both handled here rather than left to the caller:
--
--   * Subtracting across a month boundary would report the whole previous
--     month as one day's outflow. The LAG is partitioned by month, so it
--     simply does not reach back.
--   * The first snapshot we hold for a month is not necessarily the month's
--     first session — on the day this pipeline was first deployed it was
--     mid-month. Treating that MTD total as one day's flow would invent a
--     spike on an arbitrary day. So the opening snapshot counts as a daily
--     flow ONLY when its date is the first session of that month in our own
--     tape; otherwise the flow is NULL and `flow_basis` says why.
CREATE OR REPLACE VIEW fact_investor_flow_daily AS
WITH month_open AS (
    SELECT date_trunc('month', trade_date)::date AS month_start,
           min(trade_date)                       AS first_session
    FROM public.b3_cotahist
    WHERE tpmerc = '010'
    GROUP BY 1
),
snap AS (
    SELECT
        i.reference_date,
        i.investor_type,
        date_trunc('month', i.reference_date)::date AS month_start,
        i.compras_brl_mil,
        i.vendas_brl_mil,
        lag(i.compras_brl_mil) OVER w AS prev_compras,
        lag(i.vendas_brl_mil)  OVER w AS prev_vendas
    FROM public.b3_investor_participation i
    WINDOW w AS (
        PARTITION BY i.investor_type, date_trunc('month', i.reference_date)
        ORDER BY i.reference_date
    )
)
SELECT
    s.reference_date,
    s.investor_type,
    CASE
        WHEN s.prev_compras IS NOT NULL THEN 'delta'
        WHEN s.reference_date = mo.first_session THEN 'month_open'
        ELSE 'unknown_opening_snapshot'
    END AS flow_basis,
    CASE
        WHEN s.prev_compras IS NOT NULL THEN s.compras_brl_mil - s.prev_compras
        WHEN s.reference_date = mo.first_session THEN s.compras_brl_mil
        ELSE NULL
    END AS compras_brl_mil,
    CASE
        WHEN s.prev_vendas IS NOT NULL THEN s.vendas_brl_mil - s.prev_vendas
        WHEN s.reference_date = mo.first_session THEN s.vendas_brl_mil
        ELSE NULL
    END AS vendas_brl_mil,
    CASE
        WHEN s.prev_compras IS NOT NULL
            THEN (s.compras_brl_mil - s.prev_compras) - (s.vendas_brl_mil - s.prev_vendas)
        WHEN s.reference_date = mo.first_session
            THEN s.compras_brl_mil - s.vendas_brl_mil
        ELSE NULL
    END AS net_brl_mil,
    -- The cumulative figures, kept so a consumer can verify the difference
    -- against the published snapshot instead of trusting this view.
    s.compras_brl_mil AS mtd_compras_brl_mil,
    s.vendas_brl_mil  AS mtd_vendas_brl_mil
FROM snap s
LEFT JOIN month_open mo ON mo.month_start = s.month_start;

COMMENT ON VIEW fact_investor_flow_daily IS
    'Daily buy/sell/net flow by investor type, in R$ thousands, derived as the first difference of B3''s month-to-date snapshots. flow_basis is delta (a real one-session difference), month_open (the month''s first session, where MTD equals the day) or unknown_opening_snapshot (we hold no earlier snapshot in that month, so the day''s flow is NULL rather than the whole month lumped onto one date). B3 publishes these with a T+2 lag.';

-- =============================================================================
-- Public read contract (schema api). Owner-privileged, same stance as 19:
-- security_invoker = false so a grant here never implies a grant on the
-- landing tables.
-- =============================================================================

CREATE OR REPLACE VIEW api.short_interest AS
SELECT
    s.trade_date,
    s.codneg              AS ticker,
    s.asset_name,
    s.isin,
    s.b3_sector           AS sector,
    s.b3_sector_top       AS sector_top,
    s.categoria           AS instrument_category,
    s.short_qty           AS short_quantity,
    s.short_brl           AS short_value,
    s.pct_float,
    s.float_basis,
    s.float_denominator,
    s.days_to_cover,
    s.adtv_brl_21         AS adtv_value_21,
    s.adtv_sessions,
    s.taxa_doador_pct     AS lender_rate_pct,
    s.taxa_tomador_pct    AS borrower_rate_pct,
    s.num_contratos       AS contracts
FROM fact_short_interest_daily s;

ALTER VIEW api.short_interest SET (security_invoker = false);
GRANT SELECT ON api.short_interest TO anon, authenticated;

COMMENT ON VIEW api.short_interest IS
    'Short interest per (ticker, trade_date) from B3''s securities-lending book: balance, % of float (read float_basis — index_free_float and shares_outstanding are different denominators), days to cover vs 21-session ADTV, and lending rates in percentage points a.a. History starts when SILO began capturing: B3 retains only ~21 business days.';

CREATE OR REPLACE VIEW api.short_interest_by_sector AS
SELECT
    v.trade_date,
    v.b3_sector AS sector,
    v.tickers,
    v.short_brl AS short_value,
    v.short_brl_equities AS short_value_equities,
    v.short_qty AS short_quantity
FROM vw_short_by_sector v;

ALTER VIEW api.short_interest_by_sector SET (security_invoker = false);
GRANT SELECT ON api.short_interest_by_sector TO anon, authenticated;

COMMENT ON VIEW api.short_interest_by_sector IS
    'Short balance by B3 sector per session. Tickers with no published sector are bucketed as Não classificado, never dropped.';

CREATE OR REPLACE VIEW api.investor_flow AS
SELECT
    f.reference_date,
    f.investor_type,
    f.flow_basis,
    f.compras_brl_mil AS buy_value_thousands,
    f.vendas_brl_mil  AS sell_value_thousands,
    f.net_brl_mil     AS net_value_thousands,
    f.mtd_compras_brl_mil AS mtd_buy_value_thousands,
    f.mtd_vendas_brl_mil  AS mtd_sell_value_thousands
FROM fact_investor_flow_daily f;

ALTER VIEW api.investor_flow SET (security_invoker = false);
GRANT SELECT ON api.investor_flow TO anon, authenticated;

COMMENT ON VIEW api.investor_flow IS
    'Daily net flow by investor type (R$ thousands), differenced from B3''s month-to-date participation snapshots, T+2. Rows with flow_basis = unknown_opening_snapshot carry NULL flows on purpose — see fact_investor_flow_daily.';

-- Dashboards read these through the analytical layer directly (see CLAUDE.md:
-- "Evidence dashboards may keep reading dim_/fact_*"), so the landing tables
-- stay closed to anon exactly as 12_grants_and_rls.sql leaves them.
REVOKE ALL ON TABLE b3_lending_open_position         FROM anon, authenticated;
REVOKE ALL ON TABLE b3_lending_rate                  FROM anon, authenticated;
REVOKE ALL ON TABLE b3_investor_participation         FROM anon, authenticated;
REVOKE ALL ON TABLE b3_investor_participation_monthly FROM anon, authenticated;
REVOKE ALL ON TABLE b3_index_portfolio                FROM anon, authenticated;
REVOKE ALL ON TABLE b3_instrument_registry            FROM anon, authenticated;
REVOKE ALL ON TABLE vw_b3_adtv_21                     FROM anon, authenticated;

GRANT SELECT ON dim_ticker_float            TO anon, authenticated;
GRANT SELECT ON fact_short_interest_daily   TO anon, authenticated;
GRANT SELECT ON vw_short_by_sector          TO anon, authenticated;
GRANT SELECT ON fact_investor_flow_daily    TO anon, authenticated;
