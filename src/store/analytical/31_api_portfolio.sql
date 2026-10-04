-- =============================================================================
-- 31_api_portfolio.sql
-- The portfolio-diagnosis engine's four set-based reads, served through schema
-- `api` (catalog v51, portfolio_fees v52, v55 and v56; map #510, research note
-- docs/reference/research/portfolio-diagnosis-phase0.md §2, §4, §8 slice 2-3).
--
--   api.portfolio_resolve      statement lines (names, optional CNPJs, quotas)
--                              -> candidate funds, scored, with an ambiguity flag.
--   api.portfolio_fees         per CNPJ: the fee ESTIMATED from the balancete
--                              accruals, next to the fee the fund DISCLOSED (the
--                              CVM Extrato first, then the lâmina, then cad_fi).
--   api.portfolio_lookthrough  per CNPJ: what the fund holds through its fund
--                              quotas (CDA block 2, recursively), down to the
--                              assets of CDA blocks 1, 4 and 6.
--   api.portfolio_movement     per CNPJ and month: the fund's monthly quota
--                              return against its own ANBIMA class (winsorized
--                              mean and sd, +-2 / +-3 sd), catalog v54; see the
--                              section before the closing COMMIT.
--
-- RESOLVER (portfolio_resolve). Measured on production 2026-10-03: exact
-- current names are unique (24,794 funds named since 2026-05, 0 duplicated),
-- but an obsolete legal name found the right fund 1 time in 10 by trigram
-- against CURRENT names. So the resolver searches the WHOLE name history:
-- every DENOM_SOCIAL a fund ever filed in the CDA (cvm_fi_cda_fund_name, from
-- 2005) plus the registry's current name (cvm_fund_registry.fund_name, which is
-- also what dim_fund.fund_name carries), deduplicated into the matview
-- mv_fund_name_history below (about 90k names; the 3.7M-row source has no
-- trigram index and is too large to scan per line). Names are compared after
-- public.fund_name_norm: case, accents (a fixed translate() map; the unaccent
-- extension is NOT installed on Supabase, checked 2026-10-03) and runs of
-- whitespace, nothing else. Per line, in order:
--   1. a supplied CNPJ wins: match_kind 'cnpj', one candidate, never ambiguous;
--      1b. (catalog v56) else a name that is exactly a ticker of SILO's curated
--      ETF registry (cvm_etf_registry, ticker to CNPJ, case and outer spaces
--      ignored): match_kind 'etf_ticker', one candidate, never ambiguous. An ETF
--      bought by ticker has no other route to its CNPJ: api.lookup returns
--      cnpj NULL for a ticker, and a fixed income ETF is not in COTAHIST;
--   2. else an exact normalised name: 'exact_current' (the registry name or the
--      name of the fund's newest CDA month) or 'exact_history' (a former name);
--   3. else trigram: the 25 nearest names by word distance and the 25 nearest
--      by whole-string distance (GiST KNN), best name per fund, top 5 funds.
--      similarity = public.fund_name_score of the normalised input against
--      the normalised name, 0.25 or more to count as a candidate at all:
--      greatest(similarity, word_similarity) for an input of up to four words,
--      similarity alone beyond that. word_similarity is what finds an
--      abbreviation ('XP Bancos' scores 1.0 on both XP Bancos funds and 0.13
--      by whole-string similarity, measured 2026-10-03); a line of more than
--      four words is scored by similarity() alone (public.fund_name_score).
-- Tie-break by quota: when the line carries the statement's quota and its date,
-- each candidate's cvm_fi_diario.vl_quota ON THAT DATE is read (exact date,
-- partition-pruned; the subclass closest to the quota), and a candidate whose
-- quota is within 0.5% (quota_rel_diff <= 0.005) ranks first. The pinned case:
-- XP Bancos master 35377390000106 (1.952607 on 2026-09-30) and its FIC
-- 50088190000119 (1.542011) share the words of their names and only the quota
-- separates them. A line is AMBIGUOUS when its top two candidates are within
-- 0.05 of similarity and the quota does not separate them (the top one matches
-- within 0.5% and the second does not). Nothing is ever picked silently: every
-- candidate row is returned with its rank, and ambiguous is TRUE on every row
-- of an ambiguous line.
--
-- FEES (portfolio_fees). Two kinds of number, in separate columns, never mixed:
--   * DISCLOSED (disclosed_*): the fee the fund published, ONE source per fund in
--     this order (catalog v52, owner decision on issue #515 after the coverage
--     measurement of #524): the CVM Extrato das Informacoes (cvm_fi_extrato
--     through vw_fi_extrato_latest, migration 66: a TAXA_ADM for 84.3% of the
--     active FI funds, one row per fund or class), else the lâmina (cvm_fi_lamina
--     through vw_fi_lamina_latest, newest reference month, migration 65: 15.9%),
--     else cad_fi (cvm_fund_registry taxa_adm, taxa_perfm, inf_taxa_adm,
--     inf_taxa_perfm; migration 64). The source is named in disclosed_origin
--     (extrato | lamina | cad_fi) and disclosed_source, with the filing date
--     (disclosed_as_of) and its age (disclosed_age_months, disclosed_age_days). A
--     part the source did not file is NULL, never a zero fee; lâmina classes that
--     disclose different fees give a NULL single value, the min and max, and a
--     note. Both views are read dynamically, so the file applies before they
--     exist (then the columns of the missing source are NULL and the fee falls to
--     the next source).
--     Two reading rules on the single administration fee (% a year as filed),
--     applied here and never to the stored value: a filed 0 comes back as 0 with
--     filed_zero TRUE (16.7% of the Extrato's values are 0 and the balancete books
--     a fee for most of those funds: read it as "not informed", never as a zero
--     cost); a filed value above 5 (115 of 21,962, maximum 14,638.38, scale
--     errors) is NOT the fee: disclosed_taxa_adm is NULL, implausible_filed TRUE,
--     the value as filed in taxa_adm_filed_raw. An Extrato row that exists is the
--     source even then: it does not fall through to an OLDER source. Catalog v55
--     (issue #552, measured 2026-10-03: 180 funds with an Extrato 0 and 15 above 5
--     have a lâmina fee in (0, 5], 115 and 14 of them newer than the Extrato):
--     fee_resolution says which rule applied. When the Extrato filed exactly 0 or
--     above 5, the lâmina's single fee is in (0, 5] and its reference month is
--     NEWER than the Extrato's DT_COMPTC, the newer lâmina is the source
--     ('lamina_newer'): the newer of two filed, dated documents, nothing
--     rescaled. Otherwise the Extrato stays the source as filed and a lâmina fee,
--     when there is one, is returned beside it ('extrato_lamina_beside'; none:
--     'extrato_to_check'). Either way the other document's fee comes back as
--     filed (lamina_taxa_adm*, extrato_taxa_adm_filed with extrato_as_of) and
--     extrato_scale_factor flags an Extrato above 5 that is exactly 10 or 100
--     times the lâmina within the two-decimal rounding of both. A flag only: the
--     caller treats every such fund as to be checked and sums neither value.
--     The Extrato also gives the performance fee as filed (extrato_taxa_perfm,
--     numeric, with its benchmark, method and text), entry and exit fees and the
--     custody fee. Its row is the CLASS for a CVM 175 fund: there is no subclass
--     column, so a subclass fee is not assumed (extrato_class_note). The declared
--     total expense ratio (lamina_pr_pl_despesa, with its period) comes from the
--     lâmina whatever the fee source and is never added to the administration fee.
--   * ESTIMATE from the balancete accruals (cvm_fi_balancete_resumo). The fee
--     accounts (vl_taxa_administracao = COFI 81781001, vl_taxa_performance =
--     81782000) ACCUMULATE from each fund's own fiscal-year start and are filed
--     NEGATIVE. The month's accrual is previous minus current accumulated
--     value (served POSITIVE = a cost; a negative performance accrual is a
--     reversal of an earlier provision, served as filed). Annualised as
--     accrual x 12 / NAV x 100 (% a year), NAV = vl_patrimonio_sem_resultado +
--     vl_receitas + vl_despesas of the same month (groups 6 + 7 + 8, which
--     equals the daily NAV within 0.1% for 24,408 of 25,061 funds,
--     migration 59). In the fiscal-year reset month the accumulator restarts,
--     so the accumulated fee FALLS: fiscal_reset_suspect is TRUE and the
--     estimate is NULL, never a garbage number - UNLESS cad_fi's fiscal-year
--     start (DT_INI_EXERC) falls in this month, which confirms the reset, and
--     then this month's accumulated value alone IS the month's accrual (XP
--     Bancos master: -8,791,158.76 in April, -700,478.38 in May, its first
--     fiscal month). The previous month must be the calendar month before;
--     a gap leaves the estimate NULL.
--   * ETF (catalog v56): CVM's Extrato, lâmina and cad_fi hold no fee for an
--     ETF (0 of the 178 active registry ETFs, measured 2026-10-03), so a CNPJ in
--     cvm_etf_registry gets its ticker (etf_ticker) and the fee etfsbrasil.com.br
--     prints (etf_site_*, from etf_market_snapshot): a third-party value with its
--     date, in its own columns, never in disclosed_*. Since v57 the same
--     snapshot also gives the site's cotistas and PL (etf_site_nr_cotistas,
--     etf_site_pl): descriptive facts, never summed.
-- estimate_label says, on every row, that the estimate is an estimate and why
-- one is missing. The estimate is never presented as the disclosed fee.
--
-- LOOK-THROUGH (portfolio_lookthrough). One CDA month for the whole set:
-- p_month, or by default the last COMPLETE month by the /holdings rule
-- (dashboard/sources/supabase/holdings_monthly.sql): the newest month whose
-- count of funds filing block 2 (mv_fund_holdings_monthly, kind 'quota', key
-- NULL) reaches 90% of the median of the 12 months before it - 2026-05 on
-- 2026-10-03; CVM's newest months fill in late (#476). From each root, WITH
-- RECURSIVE over block 2 (cvm_fi_cda_cotas: cnpj -> cnpj_cota, rows of one
-- holder and held fund summed first, since the key also carries tp_fundo,
-- tp_aplic and tp_negoc), CYCLE-guarded on the held CNPJ (the root is the
-- depth-0 node, so a fund that holds its own holder is caught at once), depth
-- capped by p_max_depth (1..6, default 4). Every node - root included - lists
-- its own direct holdings:
--   block 1 cvm_fi_cda              government bonds ('Títulos Públicos'):
--                                   asset_kind 'government_bond'; repo
--                                   ('Operações Compromissadas') is NOT a
--                                   holding of the bond and is served
--                                   separately as asset_kind 'repo'; any other
--                                   block-1 tp_aplic is 'other_block1'.
--   block 2 cvm_fi_cda_cotas        fund quotas: 'fund_quota' (looked through:
--                                   the held fund's own rows follow at
--                                   depth + 1), 'fund_quota_unfiled' (the held
--                                   fund filed no CDA that month: an FII, a
--                                   FIDC, an offshore fund, a late filer),
--                                   'fund_quota_depth_cap' (not expanded:
--                                   p_max_depth reached), 'fund_quota_cycle'
--                                   (the held fund is already on the path;
--                                   is_cycle TRUE).
--   block 4 cvm_fi_cda_acoes        'stock' (Ações, shares lent out, units),
--                                   'debenture' (tp_aplic 'Debêntures', the
--                                   R$788.9bn of 2026-05; issuer_code = ISIN
--                                   characters 3-6, never a CNPJ), anything
--                                   else 'other_block4' (BDRs, options,
--                                   borrowed-share liabilities...) as filed.
--   block 6 cvm_fi_cda_debentures   'private_credit': issuer_cnpj only when
--                                   PF_PJ_EMISSOR says PJ (a CPF is never
--                                   served as a CNPJ), indexer as filed.
-- A fund with no CDA filing at all that month yields one row 'no_cda_filing'.
-- WEIGHTS. weight_in_root = node weight x value / NAV of the holder, node
-- weight = product of value / holder NAV down the path (root = 1). NAV is
-- fact_fund_monthly.vl_patrim_liq (FI, the month's last daily NAV) at the same
-- month as the CDA position - NOT the CDA blocks' own total, because blocks 3,
-- 5, 7 and 8 are not ingested and their sum is not the NAV. A holder with no
-- NAV that month leaves the weight NULL below it, never guessed. A fund reached
-- by two paths appears once per path, each with its own weight: sum
-- weight_in_root over leaf rows (anything but 'fund_quota') for the exposure.
-- Weights cover blocks 1, 2, 4 and 6 only, so they need not sum to 1.
--
-- BIG TABLES. cvm_fi_cda_acoes (12 GB) and cvm_fi_cda_cotas (10 GB) have no
-- index on period. Every read here is driven from the CNPJ set at one period,
-- so it is an index probe on uq_fi_cda_acoes / uq_fi_cda_cotas / uq_fi_cda /
-- uq_fi_cda_debentures (cnpj, period, ...). Measured on production 2026-10-03:
-- the recursion for XP Bancos FIC + BB RF CP Automático FIC at 2026-05 read 37
-- buffers in 0.4 ms. The anon role's statement_timeout is 3 s.
--
-- ROW CAP. The api.assert_row_cap pattern from 19: fetch one page plus one row
-- (LIMIT 1001) and REFUSE with 22023 above 1000, never trim. No cursor. The
-- resolver also refuses above 200 lines up front (200 lines x 5 candidates is
-- exactly one page), the other two above 200 CNPJs.
--
-- PRIVILEGES. Same model as 19 and 24: SECURITY DEFINER with an empty pinned
-- search_path, every relation and pg_trgm operator schema-qualified (pg_trgm
-- lives in `public` on production and in CI, checked 2026-10-03); EXECUTE
-- revoked from PUBLIC and granted to anon / authenticated and to silo_api.
-- The matview and public.fund_name_norm are internal: no client grant.
--
-- Ordering: after 19 (api.assert_row_cap), 04 (fact_fund_monthly) and 30
-- (mv_fund_holdings_monthly). The guard below fails the apply loudly if any is
-- missing.
-- =============================================================================

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL max_parallel_workers_per_gather = 0;
SET LOCAL jit = off;

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '31_api_portfolio.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.fact_fund_monthly') IS NULL THEN
        RAISE EXCEPTION '31_api_portfolio.sql weighs holdings by fact_fund_monthly; apply 04_fact_fund_monthly.sql first';
    END IF;
    IF to_regclass('public.mv_fund_holdings_monthly') IS NULL THEN
        RAISE EXCEPTION '31_api_portfolio.sql picks the default CDA month from mv_fund_holdings_monthly; apply 30_fund_holdings.sql first';
    END IF;
    IF to_regclass('public.cvm_fi_cda_fund_name') IS NULL
       OR to_regclass('public.cvm_fi_balancete_resumo') IS NULL THEN
        RAISE EXCEPTION '31_api_portfolio.sql needs cvm_fi_cda_fund_name (migration 60) and cvm_fi_balancete_resumo (migrations 59, 61)';
    END IF;
    IF to_regprocedure('public.word_similarity(text, text)') IS NULL THEN
        RAISE EXCEPTION '31_api_portfolio.sql needs pg_trgm in schema public (migration 24)';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- fund_name_norm - the one name normalisation, used on both sides
-- ---------------------------------------------------------------------------
-- Case, accents and whitespace only. translate() first, on a fixed map of the
-- Portuguese accented letters in both cases, so lower() has only ASCII left to
-- fold whatever the database collation; then runs of whitespace become one
-- space. No abbreviation expansion, no punctuation removal: a guess there
-- would be a name the fund never filed.
CREATE OR REPLACE FUNCTION public.fund_name_norm(p_name TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $fn$
    SELECT pg_catalog.btrim(pg_catalog.regexp_replace(pg_catalog.lower(pg_catalog.translate(
               p_name,
               'ÁÀÂÃÄáàâãäÉÈÊËéèêëÍÌÎÏíìîïÓÒÔÕÖóòôõöÚÙÛÜúùûüÇçÑñ',
               'AAAAAaaaaaEEEEeeeeIIIIiiiiOOOOOoooooUUUUuuuuCcNn')),
           '\s+', ' ', 'g'))
$fn$;

REVOKE ALL ON FUNCTION public.fund_name_norm(TEXT) FROM PUBLIC;

COMMENT ON FUNCTION public.fund_name_norm(TEXT) IS
    'Internal (31_api_portfolio.sql). A fund name compared by the portfolio resolver: accents removed by a fixed map, lower-cased, whitespace runs collapsed. Nothing else is changed.';

-- ---------------------------------------------------------------------------
-- fund_name_score - how alike an input name and a filed name are, 0..1
-- ---------------------------------------------------------------------------
-- similarity() of the two normalised strings; and, for an input of at most four
-- words (an abbreviation such as 'XP Bancos'), the larger of that and
-- word_similarity(), which asks how much of the input sits inside the filed
-- name. A long input is scored by similarity() alone: word_similarity of a
-- sentence-long name against a different long name inflates (measured
-- 2026-10-03: 0.84 for an unrelated fund).
CREATE OR REPLACE FUNCTION public.fund_name_score(p_input TEXT, p_name TEXT)
RETURNS REAL
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
SET search_path = ''
AS $fn$
    SELECT CASE
        WHEN pg_catalog.cardinality(pg_catalog.string_to_array(p_input, ' ')) <= 4
            THEN greatest(public.similarity(p_input, p_name),
                          public.word_similarity(p_input, p_name))
        ELSE public.similarity(p_input, p_name)
    END
$fn$;

REVOKE ALL ON FUNCTION public.fund_name_score(TEXT, TEXT) FROM PUBLIC;

COMMENT ON FUNCTION public.fund_name_score(TEXT, TEXT) IS
    'Internal (31_api_portfolio.sql). Trigram score of a normalised input against a normalised filed name: similarity(), or greatest(similarity, word_similarity) when the input has at most four words.';

-- ---------------------------------------------------------------------------
-- mv_fund_name_history - every name a fund filed, one row per (cnpj, name)
-- ---------------------------------------------------------------------------
-- Rebuilt on every apply, like 30. Nothing depends on it (functions do not
-- hold a dependency), so a plain DROP is enough.
DROP MATERIALIZED VIEW IF EXISTS public.mv_fund_name_history;

CREATE MATERIALIZED VIEW public.mv_fund_name_history AS
WITH cda AS (
    -- One row per fund and filed name: the months it was filed under.
    SELECT n.cnpj, n.denom_social AS name,
           min(n.period) AS first_period, max(n.period) AS last_period
    FROM public.cvm_fi_cda_fund_name n
    GROUP BY n.cnpj, n.denom_social
),
cda_latest AS (
    SELECT c.cnpj, max(c.last_period) AS newest FROM cda c GROUP BY c.cnpj
),
reg AS (
    SELECT r.cnpj, r.entity_type, r.fund_name AS name
    FROM public.cvm_fund_registry r
    WHERE r.fund_name IS NOT NULL AND btrim(r.fund_name) <> ''
      AND r.entity_type IN ('fi', 'fidc', 'fii', 'fip', 'fiagro')
),
src AS (
    SELECT c.cnpj, NULL::text AS entity_type, c.name, c.first_period, c.last_period,
           (c.last_period = l.newest) AS is_current, 'cda'::text AS source
    FROM cda c JOIN cda_latest l ON l.cnpj = c.cnpj
    UNION ALL
    SELECT g.cnpj, g.entity_type, g.name, NULL::date, NULL::date, TRUE, 'registry'::text
    FROM reg g
)
SELECT s.cnpj,
       public.fund_name_norm(s.name)                            AS name_norm,
       min(s.name)                                              AS name,
       -- The registry's family when it has one ('fi' first), else 'fi': the
       -- CDA is filed by FI funds only.
       COALESCE(min(s.entity_type) FILTER (WHERE s.entity_type = 'fi'),
                min(s.entity_type), 'fi')                       AS entity_type,
       min(s.first_period)                                      AS first_period,
       max(s.last_period)                                       AS last_period,
       bool_or(s.is_current)                                    AS is_current,
       string_agg(DISTINCT s.source, '+' ORDER BY s.source)     AS source
FROM src s
GROUP BY s.cnpj, public.fund_name_norm(s.name);

CREATE UNIQUE INDEX ix_mv_fund_name_history_pk ON public.mv_fund_name_history (cnpj, name_norm);
CREATE INDEX ix_mv_fund_name_history_norm ON public.mv_fund_name_history (name_norm);
CREATE INDEX ix_mv_fund_name_history_trgm
    ON public.mv_fund_name_history USING gist (name_norm public.gist_trgm_ops);

-- Supabase's default privileges grant new relations in public to the client
-- roles; this one is internal to the resolver.
REVOKE ALL ON public.mv_fund_name_history FROM PUBLIC, anon, authenticated;

COMMENT ON MATERIALIZED VIEW public.mv_fund_name_history IS
    'Internal (31_api_portfolio.sql): every name a fund filed, one row per (cnpj, normalised name), from cvm_fi_cda_fund_name (CDA DENOM_SOCIAL, first/last month filed) and cvm_fund_registry.fund_name (the current registry name, no period). is_current = the registry name or the name of the fund''s newest CDA month. Read by api.portfolio_resolve through its GiST trigram index.';

-- ---------------------------------------------------------------------------
-- portfolio_resolve - statement lines to candidate funds
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.portfolio_resolve(
    p_names       TEXT[],                 -- one statement line each, the name as printed; NULL entries allowed
    p_cnpjs       TEXT[]    DEFAULT NULL, -- same length: a CNPJ the statement prints for the line wins (punctuation ignored)
    p_quotas      NUMERIC[] DEFAULT NULL, -- same length: the statement's quota value for the line, for the tie-break
    p_quota_dates DATE[]    DEFAULT NULL  -- same length: the date that quota refers to (a cvm_fi_diario session)
)
RETURNS TABLE (
    line_no        INT,      -- 1-based position in p_names
    input_name     TEXT,     -- the line's name as sent
    candidate_cnpj TEXT,     -- NULL only when the line found no candidate
    candidate_name TEXT,     -- the fund's current name (registry, else its newest CDA name)
    matched_name   TEXT,     -- the name in the history that matched, as filed
    matched_period DATE,     -- last CDA month that name was filed under; NULL for a registry-only name
    entity_type    TEXT,     -- fi | fidc | fii | fip | fiagro (registry family; CDA-only names are fi)
    match_kind     TEXT,     -- cnpj | etf_ticker (v56) | exact_current | exact_history | trigram
    similarity     NUMERIC,  -- greatest(similarity, word_similarity) of the normalised names, 0..1; NULL when no name was sent
    rank           INT,      -- 1 = best candidate of the line
    quota_on_date  NUMERIC,  -- the candidate's vl_quota on p_quota_dates[line]; NULL when not sent or not filed that day
    quota_rel_diff NUMERIC,  -- |quota_on_date - quota| / quota; <= 0.005 counts as a match
    ambiguous      BOOLEAN,  -- TRUE on every row of a line whose top two are within 0.05 and the quota does not separate them
    reason         TEXT      -- why this candidate, in words
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_n INT := COALESCE(cardinality(p_names), cardinality(p_cnpjs), 0);
BEGIN
    IF v_n = 0 THEN
        RAISE EXCEPTION
            'portfolio_resolve needs p_names (one statement line each) or p_cnpjs: there is nothing to resolve'
            USING ERRCODE = '22023';
    END IF;
    IF v_n > 200 THEN
        RAISE EXCEPTION
            'portfolio_resolve: refused, % lines is more than 200. Up to 5 candidates per line must fit one 1000-row page, and SILO never returns a silently truncated result. To fix: send at most 200 lines per call and split the statement.',
            v_n
            USING ERRCODE = '22023',
                  DETAIL  = 'Every response is one page of at most 1000 rows; 200 lines x 5 candidates is that page.',
                  HINT    = 'Send at most 200 lines per call.';
    END IF;
    IF (p_names IS NOT NULL AND cardinality(p_names) <> v_n)
       OR (p_cnpjs IS NOT NULL AND cardinality(p_cnpjs) <> v_n)
       OR (p_quotas IS NOT NULL AND cardinality(p_quotas) <> v_n)
       OR (p_quota_dates IS NOT NULL AND cardinality(p_quota_dates) <> v_n) THEN
        RAISE EXCEPTION
            'portfolio_resolve: p_names, p_cnpjs, p_quotas and p_quota_dates are parallel arrays, one entry per statement line; every array sent must have % entries (send NULL inside an array for a line without that value)',
            v_n
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH lines AS (
        SELECT g.i AS line_no,
               p_names[g.i] AS input_name,
               public.fund_name_norm(NULLIF(btrim(p_names[g.i]), '')) AS nn,
               CASE WHEN NULLIF(regexp_replace(COALESCE(p_cnpjs[g.i], ''), '\D', '', 'g'), '') IS NULL
                    THEN NULL
                    ELSE lpad(regexp_replace(p_cnpjs[g.i], '\D', '', 'g'), 14, '0')
               END AS in_cnpj,
               p_quotas[g.i] AS q,
               p_quota_dates[g.i] AS qd
        FROM generate_series(1, v_n) AS g(i)
    ),
    -- 1. A supplied CNPJ wins.
    by_cnpj AS (
        SELECT l.line_no, l.in_cnpj AS cnpj, 'cnpj'::text AS kind,
               best.name AS matched_name, best.last_period AS matched_period,
               best.score AS sim
        FROM lines l
        LEFT JOIN LATERAL (
            SELECT h.name, h.last_period,
                   CASE WHEN l.nn IS NULL THEN NULL
                        ELSE public.fund_name_score(l.nn, h.name_norm)::numeric
                   END AS score
            FROM public.mv_fund_name_history h
            WHERE h.cnpj = l.in_cnpj
            ORDER BY CASE WHEN l.nn IS NULL THEN 0
                          ELSE public.fund_name_score(l.nn, h.name_norm) END DESC,
                     h.is_current DESC, h.last_period DESC NULLS FIRST, h.name
            LIMIT 1
        ) best ON TRUE
        WHERE l.in_cnpj IS NOT NULL
    ),
    -- 1b. An ETF ticker (catalog v56): the name is exactly a ticker of SILO's
    --     curated ETF registry. One candidate per line; exact and trigram skip it.
    by_etf AS (
        SELECT l.line_no, e.cnpj, 'etf_ticker'::text AS kind,
               e.fund_name AS matched_name, NULL::date AS matched_period,
               1.0::numeric AS sim
        FROM lines l
        JOIN public.cvm_etf_registry e ON e.ticker = upper(btrim(l.input_name))
        WHERE l.in_cnpj IS NULL AND l.nn IS NOT NULL AND e.cnpj IS NOT NULL
    ),
    -- 2. An exact normalised name, anywhere in the history.
    exact AS (
        SELECT l.line_no, h.cnpj,
               CASE WHEN bool_or(h.is_current) THEN 'exact_current' ELSE 'exact_history' END AS kind,
               min(h.name) AS matched_name, max(h.last_period) AS matched_period,
               1.0::numeric AS sim
        FROM lines l
        JOIN public.mv_fund_name_history h ON h.name_norm = l.nn
        WHERE l.in_cnpj IS NULL AND l.nn IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM by_etf b WHERE b.line_no = l.line_no)
        GROUP BY l.line_no, h.cnpj
    ),
    -- 3. Trigram, only where nothing matched exactly.
    fuzzy AS (
        SELECT l.line_no, f.cnpj, 'trigram'::text AS kind,
               f.name AS matched_name, f.last_period AS matched_period, f.score AS sim
        FROM lines l
        CROSS JOIN LATERAL (
            SELECT DISTINCT ON (k.cnpj) k.cnpj, k.name, k.last_period, k.score
            FROM (
                SELECT x.cnpj, x.name, x.last_period,
                       public.fund_name_score(l.nn, x.name_norm)::numeric AS score
                FROM (
                    (SELECT h.cnpj, h.name, h.name_norm, h.last_period
                     FROM public.mv_fund_name_history h
                     ORDER BY l.nn OPERATOR(public.<<->) h.name_norm
                     LIMIT 25)
                    UNION
                    (SELECT h.cnpj, h.name, h.name_norm, h.last_period
                     FROM public.mv_fund_name_history h
                     ORDER BY l.nn OPERATOR(public.<->) h.name_norm
                     LIMIT 25)
                ) x
            ) k
            -- A nearest neighbour is not a match: below 0.25 the names share
            -- next to nothing, and the line reports no candidate instead.
            WHERE k.score >= 0.25
            ORDER BY k.cnpj, k.score DESC, k.last_period DESC NULLS FIRST, k.name
        ) f
        WHERE l.in_cnpj IS NULL AND l.nn IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM exact e WHERE e.line_no = l.line_no)
          AND NOT EXISTS (SELECT 1 FROM by_etf b WHERE b.line_no = l.line_no)
    ),
    fuzzy_top AS (
        SELECT z.line_no, z.cnpj, z.kind, z.matched_name, z.matched_period, z.sim
        FROM (
            SELECT fz.*, row_number() OVER (PARTITION BY fz.line_no
                                            ORDER BY fz.sim DESC, fz.cnpj) AS rn
            FROM fuzzy fz
        ) z
        WHERE z.rn <= 5
    ),
    cand AS (
        SELECT * FROM by_cnpj
        UNION ALL SELECT * FROM by_etf
        UNION ALL SELECT * FROM exact
        UNION ALL SELECT * FROM fuzzy_top
    ),
    scored AS (
        SELECT c.line_no, c.cnpj, c.kind, c.matched_name, c.matched_period, c.sim,
               -- an ETF the name history does not hold keeps the registry's name (v56)
               CASE WHEN c.kind = 'etf_ticker' THEN COALESCE(cur.name, c.matched_name)
                    ELSE cur.name END AS candidate_name,
               cur.entity_type,
               qq.vl_quota AS quota_on_date,
               CASE WHEN l.q IS NULL OR l.q = 0 OR qq.vl_quota IS NULL THEN NULL
                    ELSE abs(qq.vl_quota - l.q) / abs(l.q) END AS rel_diff,
               (l.q IS NOT NULL AND l.qd IS NOT NULL) AS quota_sent
        FROM cand c
        JOIN lines l ON l.line_no = c.line_no
        LEFT JOIN LATERAL (
            -- The current name: the registry's, else the newest CDA name.
            SELECT h.name, h.entity_type
            FROM public.mv_fund_name_history h
            WHERE h.cnpj = c.cnpj
            ORDER BY (h.source LIKE '%registry%') DESC, h.is_current DESC,
                     h.last_period DESC NULLS LAST, h.name
            LIMIT 1
        ) cur ON TRUE
        LEFT JOIN LATERAL (
            -- Exact date only: a quota is never carried from another session.
            SELECT d.vl_quota
            FROM public.cvm_fi_diario d
            WHERE l.q IS NOT NULL AND l.qd IS NOT NULL
              AND d.cnpj = c.cnpj
              AND d.dt_comptc = l.qd
              AND d.vl_quota IS NOT NULL
            ORDER BY abs(d.vl_quota - l.q), d.id_subclasse
            LIMIT 1
        ) qq ON TRUE
    ),
    ranked AS (
        SELECT s.*,
               (s.rel_diff IS NOT NULL AND s.rel_diff <= 0.005) AS quota_ok,
               row_number() OVER (
                   PARTITION BY s.line_no
                   ORDER BY (s.rel_diff IS NOT NULL AND s.rel_diff <= 0.005) DESC,
                            s.sim DESC NULLS LAST,
                            s.rel_diff ASC NULLS LAST,
                            s.cnpj
               )::int AS rk,
               count(*) OVER (PARTITION BY s.line_no)::int AS n_cand
        FROM scored s
    ),
    verdict AS (
        SELECT r1.line_no,
               CASE
                   WHEN r1.kind IN ('cnpj', 'etf_ticker') OR r1.n_cand = 1 THEN FALSE
                   WHEN r1.quota_ok AND NOT COALESCE(r2.quota_ok, FALSE) THEN FALSE
                   ELSE (COALESCE(r1.sim, 0) - COALESCE(r2.sim, 0)) < 0.05
               END AS ambiguous,
               r1.sim AS sim1, r2.sim AS sim2, r1.quota_ok AS q1, r2.quota_ok AS q2
        FROM ranked r1
        LEFT JOIN ranked r2 ON r2.line_no = r1.line_no AND r2.rk = 2
        WHERE r1.rk = 1
    ),
    page (line_no, input_name, candidate_cnpj, candidate_name, matched_name,
          matched_period, entity_type, match_kind, similarity, rank,
          quota_on_date, quota_rel_diff, ambiguous, reason) AS (
        SELECT l.line_no, l.input_name, r.cnpj, r.candidate_name, r.matched_name,
               r.matched_period, r.entity_type, r.kind, round(r.sim, 4), r.rk,
               r.quota_on_date, round(r.rel_diff, 6),
               COALESCE(v.ambiguous, FALSE),
               CASE
                   WHEN l.nn IS NULL AND l.in_cnpj IS NULL THEN
                       'empty line: no name and no CNPJ'
                   WHEN r.cnpj IS NULL THEN
                       'no candidate: the name matches no fund name SILO holds'
                   WHEN r.kind = 'cnpj' AND r.candidate_name IS NULL THEN
                       'CNPJ supplied by the statement; SILO holds no registry or CDA name for it'
                   WHEN r.kind = 'cnpj' THEN
                       'CNPJ supplied by the statement'
                   WHEN r.kind = 'etf_ticker' THEN
                       'the name is the ticker of an ETF in SILO''s curated ETF registry (cvm_etf_registry, ticker to CNPJ)'
                   WHEN r.kind = 'exact_current' THEN
                       'exact match on the fund''s current name'
                   WHEN r.kind = 'exact_history' THEN
                       'exact match on a former name'
                       || COALESCE(', last filed ' || to_char(r.matched_period, 'YYYY-MM'), '')
                   ELSE 'trigram match on '
                       || CASE WHEN r.matched_period IS NULL THEN 'the registry name'
                               ELSE 'a name last filed ' || to_char(r.matched_period, 'YYYY-MM') END
               END
               || CASE
                   WHEN r.cnpj IS NULL OR NOT r.quota_sent THEN ''
                   WHEN r.quota_on_date IS NULL THEN
                       '; no quota filed on ' || l.qd::text
                   WHEN r.quota_ok THEN
                       '; quota on ' || l.qd::text || ' matches the statement within 0.5%'
                   ELSE '; quota on ' || l.qd::text || ' differs from the statement by '
                        || to_char(r.rel_diff * 100, 'FM999990.00') || '%'
               END
               || CASE
                   WHEN r.rk = 1 AND v.ambiguous THEN
                       '; AMBIGUOUS: the top two candidates score '
                       || to_char(v.sim1, 'FM0.000') || ' and ' || to_char(v.sim2, 'FM0.000')
                       || ' and the quota does not separate them'
                   WHEN r.rk = 1 AND r.n_cand > 1 AND v.q1 AND NOT COALESCE(v.q2, FALSE)
                        AND (COALESCE(v.sim1, 0) - COALESCE(v.sim2, 0)) < 0.05 THEN
                       '; chosen by the quota'
                   ELSE ''
               END
        FROM lines l
        LEFT JOIN ranked r ON r.line_no = l.line_no
        LEFT JOIN verdict v ON v.line_no = l.line_no
        ORDER BY l.line_no, r.rk NULLS FIRST
        LIMIT 1001
    )
    SELECT g.line_no, g.input_name, g.candidate_cnpj, g.candidate_name, g.matched_name,
           g.matched_period, g.entity_type, g.match_kind, g.similarity, g.rank,
           g.quota_on_date, g.quota_rel_diff, g.ambiguous, g.reason
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'portfolio_resolve')
    ORDER BY g.line_no, g.rank NULLS FIRST
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.portfolio_resolve(TEXT[], TEXT[], NUMERIC[], DATE[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.portfolio_resolve(TEXT[], TEXT[], NUMERIC[], DATE[])
    TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.portfolio_resolve(TEXT[], TEXT[], NUMERIC[], DATE[]) TO silo_api;

COMMENT ON FUNCTION api.portfolio_resolve(TEXT[], TEXT[], NUMERIC[], DATE[]) IS
    'Statement lines to candidate funds. One row per line and candidate (up to 5), ranked: a CNPJ the line carries wins (match_kind cnpj); else a name that is exactly a ticker of SILO''s curated ETF registry (cvm_etf_registry) gives that ETF''s CNPJ (etf_ticker, v56: api.lookup returns no CNPJ for a ticker); else an exact match on any name the fund ever filed, case, accents and whitespace ignored (exact_current: the registry name or the newest CDA name; exact_history: a former name, matched_period = the last CDA month it was filed under); else trigram over the whole name history (CDA DENOM_SOCIAL since 2005 plus the registry), similarity = greatest(similarity, word_similarity), so an abbreviation scores high. With p_quotas and p_quota_dates the candidate''s cvm_fi_diario quota on that exact date is compared, and one within 0.5% ranks first: that is how the XP Bancos master and FIC (same words, quotas 1.952607 and 1.542011 on 2026-09-30) are told apart. ambiguous is TRUE on every row of a line whose top two candidates score within 0.05 and the quota does not separate them: SILO never picks silently, the caller decides. Arrays are parallel, one entry per line. More than 200 lines RAISES 22023; the result is at most one 1000-row page.';

-- ---------------------------------------------------------------------------
-- portfolio_fees - the disclosed fee, and a separate estimate from the balancete
-- ---------------------------------------------------------------------------
-- The return table grew (catalog v52, again in v55): CREATE OR REPLACE cannot change a return
-- type, so the function is dropped and created again inside this file's
-- transaction. Nothing depends on it; its grants are issued below.
DROP FUNCTION IF EXISTS api.portfolio_fees(TEXT[], DATE);
CREATE OR REPLACE FUNCTION api.portfolio_fees(
    p_cnpjs TEXT[],              -- the funds, 14-digit CNPJs (punctuation ignored); at most 200
    p_month DATE DEFAULT NULL    -- the balancete month (any day of it); NULL = each fund's newest balancete
)
RETURNS TABLE (
    cnpj                     TEXT,
    fund_name                TEXT,     -- the registry name
    month                    DATE,     -- the balancete month, as filed (month-end); NULL = none filed
    nav                      NUMERIC,  -- groups 6 + 7 + 8 of that month (the NAV the estimate divides by)
    adm_fee_flow             NUMERIC,  -- ESTIMATE: R$ administration fee accrued in the month, POSITIVE = cost; NULL when not estimable
    adm_fee_pct_annual_est   NUMERIC,  -- ESTIMATE: adm_fee_flow x 12 / nav x 100, % a year
    perf_fee_flow            NUMERIC,  -- ESTIMATE: R$ performance fee accrued in the month; negative = a provision reversed
    perf_fee_pct_annual_est  NUMERIC,  -- ESTIMATE: perf_fee_flow x 12 / nav x 100, % a year
    fiscal_reset_suspect     BOOLEAN,  -- TRUE: the accumulated fee fell (or cad_fi says the fiscal year starts this month)
    disclosed_taxa_adm       NUMERIC,  -- DISCLOSED administration fee, % a year as filed; NULL = not disclosed (never zero) or a filed value above 5 (implausible_filed); a filed 0 stays 0 (filed_zero)
    disclosed_taxa_adm_min   NUMERIC,  -- lowest administration fee disclosed across the fund's classes (lâmina taxa_adm_min, else taxa_adm; Extrato: the fee itself)
    disclosed_taxa_adm_max   NUMERIC,  -- highest administration fee disclosed across the fund's classes
    disclosed_taxa_perfm     TEXT,     -- DISCLOSED performance fee as filed, text (lâmina taxa_perfm; Extrato inf_taxa_perfm, its numeric parts are the extrato_* columns); NULL = not disclosed
    disclosed_taxa_adm_info  TEXT,     -- cad_fi INF_TAXA_ADM, free text, as published (cad_fi source only)
    disclosed_taxa_perfm_info TEXT,    -- cad_fi INF_TAXA_PERFM, free text, as published (cad_fi source only)
    disclosed_source         TEXT,     -- cvm_fi_extrato | cvm_fi_lamina | cvm_fund_registry (cad_fi); NULL = nothing disclosed in any
    disclosed_as_of          DATE,     -- Extrato: DT_COMPTC of the filed version; lâmina: the reference month (dt_comptc); cad_fi: the day SILO read the row (UTC-3)
    disclosed_age_months     INT,      -- months from disclosed_as_of to the end of the newest balancete month SILO holds (0 when later); NULL for cad_fi
    disclosed_n_classes      INT,      -- lâmina classes/subclasses at that reference month; Extrato: 1 (one row per fund or class); NULL for cad_fi
    disclosed_note           TEXT,     -- why a disclosed number is NULL, zero, rejected or a range, else NULL
    estimate_label           TEXT,     -- says the estimate is an estimate, and why one is missing
    -- ---- appended in catalog v52 (the existing columns above are unchanged) ----
    disclosed_origin         TEXT,     -- extrato | lamina | cad_fi: which source the disclosed_* columns came from (one per fund); NULL = none
    disclosed_age_days       INT,      -- days from disclosed_as_of to today (UTC); NULL for cad_fi
    filed_zero               BOOLEAN,  -- TRUE: the source filed an administration fee of exactly 0 - returned as 0, read it as "not informed", never as a zero cost
    implausible_filed        BOOLEAN,  -- TRUE: the source filed a fee above 5 (% a year) or below 0 - NOT returned as the fee (disclosed_taxa_adm is NULL); the value is in taxa_adm_filed_raw
    taxa_adm_filed_raw       NUMERIC,  -- the source's single administration fee exactly as filed, before the zero and above-5 rules; NULL when none or classes differ
    extrato_tp_fundo_classe  TEXT,     -- Extrato TP_FUNDO_CLASSE: FI (ICVM 555 fund) | CLASSES - FIF (CVM 175 class); only when the source is extrato
    extrato_classe_anbima    TEXT,     -- Extrato CLASSE_ANBIMA, as filed
    extrato_class_note       TEXT,     -- the scope of the Extrato row: a class fee (no subclass column) or a fund fee
    extrato_existe_taxa_perfm TEXT,    -- Extrato EXISTE_TAXA_PERFM: S | N
    extrato_taxa_perfm       NUMERIC,  -- Extrato TAXA_PERFM as filed
    extrato_param_taxa_perfm TEXT,     -- Extrato PARAM_TAXA_PERFM as filed (the benchmark)
    extrato_calc_taxa_perfm  TEXT,     -- Extrato CALC_TAXA_PERFM as filed (the method)
    extrato_inf_taxa_perfm   TEXT,     -- Extrato INF_TAXA_PERFM as filed (free text)
    extrato_existe_taxa_ingresso TEXT, -- Extrato EXISTE_TAXA_INGRESSO: S | N
    extrato_taxa_ingresso_pr NUMERIC,  -- Extrato TAXA_INGRESSO_PR as filed (%)
    extrato_taxa_ingresso_real NUMERIC, -- Extrato TAXA_INGRESSO_REAL as filed (R$)
    extrato_existe_taxa_saida TEXT,    -- Extrato EXISTE_TAXA_SAIDA: S | N
    extrato_taxa_saida_pr    NUMERIC,  -- Extrato TAXA_SAIDA_PR as filed (%)
    extrato_taxa_saida_real  NUMERIC,  -- Extrato TAXA_SAIDA_REAL as filed (R$)
    extrato_taxa_custodia_max NUMERIC, -- Extrato TAXA_CUSTODIA_MAX as filed
    lamina_pr_pl_despesa     NUMERIC,  -- DECLARED total expense ratio (lâmina PR_PL_DESPESA, % of average NAV over the period below), whatever the fee source; NULL when none or classes differ; never added to the administration fee
    lamina_dt_ini_despesa    DATE,     -- start of the period behind lamina_pr_pl_despesa
    lamina_dt_fim_despesa    DATE,     -- end of that period
    lamina_as_of             DATE,     -- the lâmina's newest reference month, read for the expense ratio and the lamina_taxa_adm* columns; NULL = no lâmina
    lamina_expense_note      TEXT,     -- why lamina_pr_pl_despesa is NULL (none filed, classes differ), else NULL
    -- ---- appended in catalog v55 (issue #552; the existing columns above are unchanged) ----
    fee_resolution           TEXT,     -- which rule set the disclosed_* columns: extrato | extrato_lamina_beside (the Extrato filed 0 or above 5 and a lâmina fee is shown beside it, older or not plausible) | extrato_to_check (the same, no lâmina fee) | lamina_newer (the Extrato filed 0 or above 5, the lâmina's single fee is in (0, 5] and NEWER: the lâmina is the source) | lamina | cad_fi; NULL = none
    lamina_taxa_adm          NUMERIC,  -- the lâmina's single administration fee as filed at lamina_as_of, whatever the source; NULL when none or classes differ; never summed with the disclosed fee
    lamina_taxa_adm_min      NUMERIC,  -- lowest administration fee the lâmina's classes disclose (taxa_adm_min, else taxa_adm)
    lamina_taxa_adm_max      NUMERIC,  -- highest
    lamina_n_classes         INT,      -- lâmina classes/subclasses at lamina_as_of
    lamina_age_months        INT,      -- months from lamina_as_of to the end of the newest balancete month SILO holds (0 when later)
    extrato_taxa_adm_filed   NUMERIC,  -- the Extrato's TAXA_ADM exactly as filed (newest version), whatever the source: 0 and values above 5 included, never rescaled
    extrato_as_of            DATE,     -- that version's DT_COMPTC
    extrato_lamina_ratio     NUMERIC,  -- extrato_taxa_adm_filed / lamina_taxa_adm, 4 decimals, when both are above 0; NULL otherwise
    extrato_scale_factor     INT,      -- 10 or 100: the Extrato filed above 5 and equals that factor times the lâmina's single fee within the two-decimal rounding of both (|extrato - k x lamina| <= k x 0.005 + 0.005); a flag ("possível erro de escala no Extrato"), never a correction; NULL otherwise
    -- ---- appended in catalog v56 (ETFs; the existing columns above are unchanged) ----
    etf_ticker               TEXT,     -- the ticker of this CNPJ in SILO's curated ETF registry (cvm_etf_registry); NULL = not an ETF SILO lists
    etf_site_taxa_adm        NUMERIC,  -- the ETF's 'Taxa de administração total' as etfsbrasil.com.br prints it (etf_market_snapshot.taxa_adm_pct, % a year), newest snapshot that has one; a THIRD-PARTY site, not a CVM filing, never in disclosed_*; NULL = none (not a zero fee)
    etf_site_as_of           DATE,     -- that snapshot's date
    etf_site_source          TEXT,     -- etf_market_snapshot.source (etfsbrasil); NULL with no snapshot
    etf_site_note            TEXT,     -- what the etf_site_* value is and is not, and why it is NULL; NULL for a CNPJ that is no ETF
    -- ---- appended in catalog v57 (ETF facts; the existing columns above are unchanged) ----
    etf_site_nr_cotistas     INT,      -- the ETF's 'Número de cotistas' as etfsbrasil.com.br prints it (etf_market_snapshot.cotistas), from the SAME snapshot as etf_site_taxa_adm (etf_site_as_of, etf_site_source); a THIRD-PARTY site, not a CVM filing; descriptive, never summed; NULL = the site printed none (not zero)
    etf_site_pl              NUMERIC   -- the ETF's 'Patrimônio líquido' in R$ as etfsbrasil.com.br prints it (etf_market_snapshot.nav: the site prints R$ MM with two decimals, stored x 1e6 by the ingest, so it resolves to R$ 10 mil), same snapshot; a THIRD-PARTY value, not a CVM filing; descriptive, never a fee base or a total; NULL = none
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_n     INT  := COALESCE(cardinality(p_cnpjs), 0);
    v_month DATE := CASE WHEN p_month IS NULL THEN NULL
                         ELSE (date_trunc('month', p_month) + INTERVAL '1 month - 1 day')::date END;
    v_bad   TEXT;
    v_ids   TEXT[];
    v_lam   JSONB := '[]'::jsonb;
    v_ext   JSONB := '[]'::jsonb;
    v_etf   JSONB := '[]'::jsonb;
BEGIN
    IF v_n = 0 THEN
        RAISE EXCEPTION 'portfolio_fees needs p_cnpjs, the funds'' 14-digit CNPJs (resolve names with portfolio_resolve)'
            USING ERRCODE = '22023';
    END IF;
    IF v_n > 200 THEN
        RAISE EXCEPTION
            'portfolio_fees: refused, % CNPJs is more than 200 per call. SILO caps a portfolio call at 200 funds. To fix: split the set into calls of at most 200.',
            v_n
            USING ERRCODE = '22023',
                  HINT = 'Send at most 200 CNPJs per call.';
    END IF;
    SELECT x INTO v_bad
    FROM unnest(p_cnpjs) AS u(x)
    WHERE x IS NULL OR regexp_replace(x, '\D', '', 'g') !~ '^[0-9]{1,14}$'
    LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'portfolio_fees: every p_cnpjs entry must be a fund''s CNPJ (up to 14 digits, punctuation ignored); got %',
            COALESCE(v_bad, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    SELECT array_agg(DISTINCT lpad(regexp_replace(x, '\D', '', 'g'), 14, '0'))
      INTO v_ids
    FROM unnest(p_cnpjs) AS u(x);

    -- The lâmina (vw_fi_lamina_latest: newest dt_comptc per cnpj and subclass,
    -- slice A, migration 65) and the Extrato (vw_fi_extrato_latest: newest
    -- dt_comptc per cnpj, migration 66) are read dynamically, so this function
    -- applies on a database that does not hold a view yet - the columns of the
    -- missing source are then NULL and the fee falls to the next source. The
    -- lâmina is read by key name (to_jsonb); the Extrato by an explicit column
    -- list, only the columns this function serves (its `raw` is not carried).
    IF to_regclass('public.vw_fi_lamina_latest') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(jsonb_agg(to_jsonb(v)), ''[]''::jsonb) '
             || 'FROM public.vw_fi_lamina_latest v WHERE v.cnpj = ANY ($1)'
        INTO v_lam USING v_ids;
    END IF;
    IF to_regclass('public.vw_fi_extrato_latest') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(jsonb_agg(jsonb_build_object('
             || '''cnpj'', v.cnpj, ''dt_comptc'', v.dt_comptc, ''age_days'', v.age_days, '
             || '''tp_fundo_classe'', v.tp_fundo_classe, ''classe_anbima'', v.classe_anbima, '
             || '''taxa_adm'', v.taxa_adm, ''taxa_custodia_max'', v.taxa_custodia_max, '
             || '''existe_taxa_perfm'', v.existe_taxa_perfm, ''taxa_perfm'', v.taxa_perfm, '
             || '''param_taxa_perfm'', v.param_taxa_perfm, ''calc_taxa_perfm'', v.calc_taxa_perfm, '
             || '''inf_taxa_perfm'', v.inf_taxa_perfm, '
             || '''existe_taxa_ingresso'', v.existe_taxa_ingresso, ''taxa_ingresso_pr'', v.taxa_ingresso_pr, '
             || '''taxa_ingresso_real'', v.taxa_ingresso_real, '
             || '''existe_taxa_saida'', v.existe_taxa_saida, ''taxa_saida_pr'', v.taxa_saida_pr, '
             || '''taxa_saida_real'', v.taxa_saida_real)), ''[]''::jsonb) '
             || 'FROM public.vw_fi_extrato_latest v WHERE v.cnpj = ANY ($1)'
        INTO v_ext USING v_ids;
    END IF;
    -- ETFs (catalog v56). CVM's Extrato, lâmina and cad_fi carry no fee for an ETF
    -- (measured 2026-10-03: 0 of the 178 active registry ETFs in any of the three,
    -- and cvm_etf_registry.taxa_adm, lifted from cad_fi, is 0 of 187). The only fee
    -- SILO holds is the etfsbrasil.com.br scrape (etf_market_snapshot, 171 of 178
    -- tickers on 2026-10-03), served in its own etf_site_* columns, never in
    -- disclosed_*. Read dynamically, like the views: a database without the table
    -- returns NULL there. Joined by the registry's TICKER, because the site's CNPJ
    -- can differ from the registry's (WRLD11 on 2026-10-03); the newest snapshot
    -- that has a fee. Catalog v57 (owner, 2026-10-03) carries the site's
    -- 'Número de cotistas' and 'Patrimônio líquido' from that SAME row, so the
    -- three share etf_site_as_of (on 2026-10-03 fee, cotistas and nav are filled
    -- for the same 171 of 178 tickers). CVM has no 2026 diário row for any
    -- registry ETF, so these are the only cotistas and PL SILO holds for one.
    IF to_regclass('public.etf_market_snapshot') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(jsonb_agg(jsonb_build_object('
             || '''ticker'', s.ticker, ''snapshot_date'', s.snapshot_date, '
             || '''taxa_adm_pct'', s.taxa_adm_pct, ''source'', s.source, ''site_cnpj'', s.cnpj, '
             || '''cotistas'', s.cotistas, ''nav'', s.nav)), ''[]''::jsonb) '
             || 'FROM (SELECT DISTINCT ON (x.ticker) x.ticker, x.snapshot_date, x.taxa_adm_pct, x.source, x.cnpj, '
             || 'x.cotistas, x.nav '
             || 'FROM public.etf_market_snapshot x '
             || 'JOIN public.cvm_etf_registry r ON r.ticker = x.ticker '
             || 'WHERE r.cnpj = ANY ($1) AND x.taxa_adm_pct IS NOT NULL '
             || 'ORDER BY x.ticker, x.snapshot_date DESC) s'
        INTO v_etf USING v_ids;
    END IF;

    RETURN QUERY
    WITH ids AS (
        SELECT unnest(v_ids) AS cnpj
    ),
    -- The lâmina rows at each fund's newest reference month. A class that
    -- stopped filing earlier is not read: its fee is stale by definition.
    lam_rows AS (
        SELECT e ->> 'cnpj' AS cnpj,
               CASE WHEN e ->> 'dt_comptc' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                    THEN left(e ->> 'dt_comptc', 10)::date END AS dt_comptc,
               CASE WHEN e ->> 'taxa_adm' ~ '^-?[0-9]+(\.[0-9]+)?$'
                    THEN (e ->> 'taxa_adm')::numeric END AS taxa_adm,
               CASE WHEN e ->> 'taxa_adm_min' ~ '^-?[0-9]+(\.[0-9]+)?$'
                    THEN (e ->> 'taxa_adm_min')::numeric END AS taxa_adm_min,
               CASE WHEN e ->> 'taxa_adm_max' ~ '^-?[0-9]+(\.[0-9]+)?$'
                    THEN (e ->> 'taxa_adm_max')::numeric END AS taxa_adm_max,
               NULLIF(btrim(e ->> 'taxa_perfm'), '') AS taxa_perfm,
               CASE WHEN e ->> 'pr_pl_despesa' ~ '^-?[0-9]+(\.[0-9]+)?$'
                    THEN (e ->> 'pr_pl_despesa')::numeric END AS pr_pl_despesa,
               CASE WHEN e ->> 'dt_ini_despesa' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                    THEN left(e ->> 'dt_ini_despesa', 10)::date END AS dt_ini_despesa,
               CASE WHEN e ->> 'dt_fim_despesa' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                    THEN left(e ->> 'dt_fim_despesa', 10)::date END AS dt_fim_despesa
        FROM jsonb_array_elements(v_lam) AS j(e)
    ),
    lam AS (
        SELECT r.cnpj,
               r.dt_comptc,
               count(*)::int AS n_classes,
               count(DISTINCT r.taxa_adm) AS n_adm,
               min(r.taxa_adm) AS adm_lo, max(r.taxa_adm) AS adm_hi,
               min(COALESCE(r.taxa_adm_min, r.taxa_adm)) AS adm_min,
               max(COALESCE(r.taxa_adm_max, r.taxa_adm)) AS adm_max,
               count(DISTINCT r.taxa_perfm) AS n_perfm,
               min(r.taxa_perfm) AS perfm,
               bool_or(r.taxa_adm IS NULL AND r.taxa_perfm IS NULL) AS has_empty,
               -- The declared expense ratio: one value only when every class
               -- filed the same one, with the period it covers.
               count(DISTINCT r.pr_pl_despesa) AS n_desp,
               min(r.pr_pl_despesa) AS desp,
               bool_or(r.pr_pl_despesa IS NULL) AS has_empty_desp,
               min(r.dt_ini_despesa) FILTER (WHERE r.pr_pl_despesa IS NOT NULL) AS desp_ini,
               max(r.dt_fim_despesa) FILTER (WHERE r.pr_pl_despesa IS NOT NULL) AS desp_fim
        FROM lam_rows r
        WHERE r.dt_comptc = (SELECT max(q.dt_comptc) FROM lam_rows q WHERE q.cnpj = r.cnpj)
        GROUP BY r.cnpj, r.dt_comptc
    ),
    -- The Extrato: one row per fund or class (the view's newest DT_COMPTC).
    ext AS (
        SELECT e ->> 'cnpj' AS cnpj,
               (e ->> 'dt_comptc')::date AS x_dt,
               (e ->> 'age_days')::int AS x_age,
               NULLIF(btrim(e ->> 'tp_fundo_classe'), '') AS x_tp,
               NULLIF(btrim(e ->> 'classe_anbima'), '') AS x_classe,
               (e ->> 'taxa_adm')::numeric AS x_adm,
               (e ->> 'taxa_custodia_max')::numeric AS x_custodia,
               NULLIF(btrim(e ->> 'existe_taxa_perfm'), '') AS x_existe_perfm,
               (e ->> 'taxa_perfm')::numeric AS x_perfm,
               NULLIF(btrim(e ->> 'param_taxa_perfm'), '') AS x_param,
               NULLIF(btrim(e ->> 'calc_taxa_perfm'), '') AS x_calc,
               NULLIF(btrim(e ->> 'inf_taxa_perfm'), '') AS x_inf,
               NULLIF(btrim(e ->> 'existe_taxa_ingresso'), '') AS x_existe_ing,
               (e ->> 'taxa_ingresso_pr')::numeric AS x_ing_pr,
               (e ->> 'taxa_ingresso_real')::numeric AS x_ing_real,
               NULLIF(btrim(e ->> 'existe_taxa_saida'), '') AS x_existe_saida,
               (e ->> 'taxa_saida_pr')::numeric AS x_saida_pr,
               (e ->> 'taxa_saida_real')::numeric AS x_saida_real
        FROM jsonb_array_elements(v_ext) AS j(e)
    ),
    reg AS (
        -- The FI row first: cad_fi is the FI registry.
        SELECT i.cnpj, rr.fund_name, rr.fetched_at, rr.taxa_adm, rr.taxa_perfm,
               rr.inf_taxa_adm, rr.inf_taxa_perfm, rr.dt_ini_exerc
        FROM ids i
        LEFT JOIN LATERAL (
            SELECT r.fund_name, r.fetched_at, r.taxa_adm, r.taxa_perfm,
                   NULLIF(btrim(r.inf_taxa_adm), '') AS inf_taxa_adm,
                   NULLIF(btrim(r.inf_taxa_perfm), '') AS inf_taxa_perfm,
                   r.dt_ini_exerc
            FROM public.cvm_fund_registry r
            WHERE r.cnpj = i.cnpj
            ORDER BY (r.entity_type = 'fi') DESC, r.entity_type
            LIMIT 1
        ) rr ON TRUE
    ),
    -- ONE disclosed source per fund, never a mix of two, in this order: the
    -- Extrato when it has a row with a parseable administration fee (a filed 0
    -- and a value above 5 count: they are read below, not skipped, so the
    -- Extrato's word is not silently replaced by an OLDER source's); else the
    -- lâmina when it gives a fee; else cad_fi. One exception (catalog v55, issue
    -- #552): when the Extrato filed exactly 0 or above 5 AND the lâmina's single
    -- fee is above 0 and at most 5 AND the lâmina's reference month is NEWER than
    -- the Extrato's DT_COMPTC, the newer lâmina is the source (lam_newer,
    -- fee_resolution 'lamina_newer'). That picks the newer of two filed, dated
    -- documents; neither value is rescaled, and the Extrato value is returned
    -- beside it as filed (extrato_taxa_adm_filed, extrato_as_of).
    disc AS (
        SELECT g.cnpj, g.fund_name, g.fetched_at, g.dt_ini_exerc,
               (x.cnpj IS NOT NULL AND x.x_adm IS NOT NULL AND NOT n.lam_newer) AS use_ext,
               (n.lam_newer
                OR ((x.cnpj IS NULL OR x.x_adm IS NULL)
                    AND l.cnpj IS NOT NULL AND (l.adm_min IS NOT NULL OR l.perfm IS NOT NULL
                                                OR l.n_perfm > 1))) AS use_lam,
               n.lam_newer, s.lam_single,
               x.x_dt, x.x_age, x.x_tp, x.x_classe, x.x_adm, x.x_custodia, x.x_existe_perfm,
               x.x_perfm, x.x_param, x.x_calc, x.x_inf, x.x_existe_ing, x.x_ing_pr,
               x.x_ing_real, x.x_existe_saida, x.x_saida_pr, x.x_saida_real,
               l.dt_comptc AS lam_dt, l.n_classes, l.n_adm, l.n_perfm, l.has_empty,
               l.adm_lo, l.adm_hi, l.adm_min, l.adm_max, l.perfm AS lam_perfm,
               l.n_desp, l.desp, l.has_empty_desp, l.desp_ini, l.desp_fim,
               g.taxa_adm, g.taxa_perfm, g.inf_taxa_adm, g.inf_taxa_perfm
        FROM reg g
        LEFT JOIN ext x ON x.cnpj = g.cnpj
        LEFT JOIN lam l ON l.cnpj = g.cnpj
        -- The lâmina's single administration fee: one value only when every class
        -- discloses the same one (the rule the lâmina source itself follows).
        CROSS JOIN LATERAL (
            SELECT CASE WHEN l.n_adm = 1 AND NOT l.has_empty THEN l.adm_lo END AS lam_single
        ) s
        CROSS JOIN LATERAL (
            SELECT COALESCE(x.x_adm IS NOT NULL AND (x.x_adm = 0 OR x.x_adm > 5)
                            AND s.lam_single > 0 AND s.lam_single <= 5
                            AND l.dt_comptc > x.x_dt, FALSE) AS lam_newer
        ) n
    ),
    cur AS (
        SELECT i.cnpj, b.*
        FROM ids i
        LEFT JOIN LATERAL (
            SELECT r.dt_comptc, r.vl_taxa_administracao AS adm_acc,
                   r.vl_taxa_performance AS perf_acc,
                   r.vl_patrimonio_sem_resultado + r.vl_receitas + r.vl_despesas AS nav
            FROM public.cvm_fi_balancete_resumo r
            WHERE r.cnpj = i.cnpj
              AND (v_month IS NULL OR r.dt_comptc = v_month)
            ORDER BY r.dt_comptc DESC
            LIMIT 1
        ) b ON TRUE
    ),
    pair AS (
        SELECT c.cnpj, c.dt_comptc, c.nav, c.adm_acc, c.perf_acc,
               p.adm_acc AS adm_prev, p.perf_acc AS perf_prev,
               d.fund_name, d.fetched_at, d.dt_ini_exerc, d.use_lam, d.lam_dt, d.n_classes,
               d.n_adm, d.n_perfm, d.has_empty, d.adm_lo, d.adm_hi, d.adm_min, d.adm_max,
               d.lam_perfm, d.taxa_adm, d.taxa_perfm, d.inf_taxa_adm, d.inf_taxa_perfm,
               d.use_ext, d.x_dt, d.x_age, d.x_tp, d.x_classe, d.x_adm, d.x_custodia,
               d.x_existe_perfm, d.x_perfm, d.x_param, d.x_calc, d.x_inf, d.x_existe_ing,
               d.x_ing_pr, d.x_ing_real, d.x_existe_saida, d.x_saida_pr, d.x_saida_real,
               d.n_desp, d.desp, d.has_empty_desp, d.desp_ini, d.desp_fim,
               d.lam_newer, d.lam_single,
               -- The calendar month before; a gap is no previous month.
               p.dt_comptc IS NOT NULL AS has_prev,
               (d.dt_ini_exerc IS NOT NULL AND c.dt_comptc IS NOT NULL
                AND extract(month FROM d.dt_ini_exerc) = extract(month FROM c.dt_comptc)) AS reset_confirmed
        FROM cur c
        JOIN disc d ON d.cnpj = c.cnpj
        LEFT JOIN LATERAL (
            SELECT r.dt_comptc, r.vl_taxa_administracao AS adm_acc,
                   r.vl_taxa_performance AS perf_acc
            FROM public.cvm_fi_balancete_resumo r
            WHERE r.cnpj = c.cnpj
              AND r.dt_comptc = (date_trunc('month', c.dt_comptc) - INTERVAL '1 day')::date
        ) p ON TRUE
    ),
    est AS (
        SELECT a.*,
               (a.reset_confirmed
                OR (a.has_prev AND a.adm_acc IS NOT NULL AND a.adm_prev IS NOT NULL
                    AND a.adm_acc > a.adm_prev)) AS reset_suspect,
               CASE
                   WHEN a.reset_confirmed THEN -a.adm_acc
                   WHEN a.has_prev AND a.adm_acc > a.adm_prev THEN NULL
                   WHEN a.has_prev THEN a.adm_prev - a.adm_acc
               END AS adm_flow,
               CASE
                   WHEN a.reset_confirmed THEN -a.perf_acc
                   WHEN a.has_prev AND a.adm_acc > a.adm_prev THEN NULL
                   WHEN a.has_prev THEN a.perf_prev - a.perf_acc
               END AS perf_flow,
               -- The newest month SILO holds for the age in months; never today's date.
               (SELECT max(z.dt_comptc) FROM public.cvm_fi_balancete_resumo z) AS newest_month,
               -- Which source, and the single administration fee exactly as it filed it.
               CASE WHEN a.use_ext THEN 'extrato'
                    WHEN a.use_lam THEN 'lamina'
                    WHEN COALESCE(a.taxa_adm, a.taxa_perfm) IS NOT NULL
                         OR COALESCE(a.inf_taxa_adm, a.inf_taxa_perfm) IS NOT NULL
                    THEN 'cad_fi' END AS origin,
               CASE WHEN a.use_ext THEN a.x_adm
                    WHEN a.use_lam THEN (CASE WHEN a.n_adm = 1 AND NOT a.has_empty THEN a.adm_lo END)
                    ELSE a.taxa_adm END AS fee_raw
        FROM pair a
    ),
    -- The owner's reading rules (issue #515, #524): a filed 0 is not a fee and a
    -- filed value above 5 is a scale error. The stored value is never rewritten;
    -- the 0 is returned as filed with a flag, the implausible value is withheld.
    flag AS (
        SELECT e.*,
               COALESCE(e.fee_raw = 0, FALSE) AS is_zero,
               COALESCE(e.fee_raw > 5 OR e.fee_raw < 0, FALSE) AS is_implausible
        FROM est e
    ),
    -- The ETF registry's ticker for each CNPJ (v56), and the site's fee by that ticker.
    etf AS (
        SELECT i.cnpj, t.ticker
        FROM ids i
        JOIN LATERAL (
            SELECT r.ticker FROM public.cvm_etf_registry r
            WHERE r.cnpj = i.cnpj
            ORDER BY r.is_active DESC NULLS LAST, r.ticker
            LIMIT 1
        ) t ON TRUE
    ),
    etf_site AS (
        SELECT e ->> 'ticker' AS ticker,
               (e ->> 'snapshot_date')::date AS s_dt,
               (e ->> 'taxa_adm_pct')::numeric AS s_fee,
               NULLIF(btrim(e ->> 'source'), '') AS s_source,
               NULLIF(btrim(e ->> 'site_cnpj'), '') AS s_cnpj,
               (e ->> 'cotistas')::int AS s_cotistas,
               (e ->> 'nav')::numeric AS s_pl
        FROM jsonb_array_elements(v_etf) AS j(e)
    ),
    page (cnpj, fund_name, month, nav, adm_fee_flow, adm_fee_pct_annual_est,
          perf_fee_flow, perf_fee_pct_annual_est, fiscal_reset_suspect,
          disclosed_taxa_adm, disclosed_taxa_adm_min, disclosed_taxa_adm_max,
          disclosed_taxa_perfm, disclosed_taxa_adm_info, disclosed_taxa_perfm_info,
          disclosed_source, disclosed_as_of, disclosed_age_months,
          disclosed_n_classes, disclosed_note, estimate_label,
          disclosed_origin, disclosed_age_days, filed_zero, implausible_filed,
          taxa_adm_filed_raw, extrato_tp_fundo_classe, extrato_classe_anbima,
          extrato_class_note, extrato_existe_taxa_perfm, extrato_taxa_perfm,
          extrato_param_taxa_perfm, extrato_calc_taxa_perfm, extrato_inf_taxa_perfm,
          extrato_existe_taxa_ingresso, extrato_taxa_ingresso_pr, extrato_taxa_ingresso_real,
          extrato_existe_taxa_saida, extrato_taxa_saida_pr, extrato_taxa_saida_real,
          extrato_taxa_custodia_max, lamina_pr_pl_despesa, lamina_dt_ini_despesa,
          lamina_dt_fim_despesa, lamina_as_of, lamina_expense_note,
          fee_resolution, lamina_taxa_adm, lamina_taxa_adm_min, lamina_taxa_adm_max,
          lamina_n_classes, lamina_age_months, extrato_taxa_adm_filed, extrato_as_of,
          extrato_lamina_ratio, extrato_scale_factor,
          etf_ticker, etf_site_taxa_adm, etf_site_as_of, etf_site_source, etf_site_note,
          etf_site_nr_cotistas, etf_site_pl) AS (
        SELECT f.cnpj, f.fund_name, f.dt_comptc, f.nav,
               f.adm_flow,
               round(f.adm_flow * 12 / NULLIF(f.nav, 0) * 100, 4),
               f.perf_flow,
               round(f.perf_flow * 12 / NULLIF(f.nav, 0) * 100, 4),
               COALESCE(f.reset_suspect, FALSE),
               -- Extrato: the fee as filed (the 0 kept, a value above 5 withheld).
               -- Lâmina: one fee only when every class discloses the same one.
               CASE WHEN f.is_implausible THEN NULL ELSE f.fee_raw END,
               CASE WHEN f.use_ext THEN (CASE WHEN f.is_implausible THEN NULL ELSE f.x_adm END)
                    WHEN f.use_lam THEN f.adm_min END,
               CASE WHEN f.use_ext THEN (CASE WHEN f.is_implausible THEN NULL ELSE f.x_adm END)
                    WHEN f.use_lam THEN f.adm_max END,
               CASE WHEN f.use_ext THEN f.x_inf
                    WHEN f.use_lam THEN (CASE WHEN f.n_perfm = 1 AND NOT f.has_empty THEN f.lam_perfm END)
                    ELSE f.taxa_perfm::text END,
               CASE WHEN f.use_ext OR f.use_lam THEN NULL ELSE f.inf_taxa_adm END,
               CASE WHEN f.use_ext OR f.use_lam THEN NULL ELSE f.inf_taxa_perfm END,
               CASE f.origin WHEN 'extrato' THEN 'cvm_fi_extrato'
                             WHEN 'lamina' THEN 'cvm_fi_lamina'
                             WHEN 'cad_fi' THEN 'cvm_fund_registry (cad_fi)' END,
               CASE f.origin WHEN 'extrato' THEN f.x_dt
                             WHEN 'lamina' THEN f.lam_dt
                             WHEN 'cad_fi' THEN (f.fetched_at AT TIME ZONE 'America/Sao_Paulo')::date END,
               CASE WHEN f.use_ext AND f.newest_month IS NOT NULL THEN
                    GREATEST(0, ((extract(year FROM f.newest_month) - extract(year FROM f.x_dt)) * 12
                                 + extract(month FROM f.newest_month) - extract(month FROM f.x_dt))::int)
                    WHEN f.use_lam AND f.newest_month IS NOT NULL THEN
                    -- 0 when the lâmina is later than the newest balancete month (as the column says; clamped since v55)
                    GREATEST(0, ((extract(year FROM f.newest_month) - extract(year FROM f.lam_dt)) * 12
                                 + extract(month FROM f.newest_month) - extract(month FROM f.lam_dt))::int) END,
               CASE WHEN f.use_ext THEN 1
                    WHEN f.use_lam THEN f.n_classes END,
               CASE
                   WHEN f.lam_newer THEN
                       'the Extrato of ' || to_char(f.x_dt, 'YYYY-MM-DD') || ' filed an administration fee of '
                       || trim_scale(f.x_adm)::text || ' (0 or above 5 % a year) and the lâmina of '
                       || to_char(f.lam_dt, 'YYYY-MM-DD') || ', newer, discloses ' || trim_scale(f.lam_single)::text
                       || ': the newer lâmina is the source (fee_resolution lamina_newer), to be checked; the Extrato value as filed is in extrato_taxa_adm_filed, never rescaled'
                   WHEN f.is_implausible THEN
                       'the ' || CASE f.origin WHEN 'extrato' THEN 'Extrato' WHEN 'lamina' THEN 'lâmina' ELSE 'cad_fi' END
                       || ' filed an administration fee of ' || trim_scale(f.fee_raw)::text
                       || ', outside 0 to 5 % a year: treated as a scale error and not used; the value as filed is in taxa_adm_filed_raw'
                   WHEN f.is_zero THEN
                       'the ' || CASE f.origin WHEN 'extrato' THEN 'Extrato' WHEN 'lamina' THEN 'lâmina' ELSE 'cad_fi' END
                       || ' filed an administration fee of exactly 0: returned as filed (filed_zero); read it as not informed, never as a zero cost'
                   WHEN f.use_lam AND (f.n_adm > 1 OR f.n_perfm > 1) THEN
                       'the fund''s ' || f.n_classes || ' classes disclose different fees: the single value is NULL, read the min and max'
                   WHEN f.use_lam AND f.has_empty THEN
                       'at least one class filed no fee: NULL is not a zero fee'
                   WHEN f.use_lam AND f.n_adm = 0 THEN
                       'the lâmina filed no administration fee: NULL is not a zero fee'
                   WHEN NOT f.use_ext AND NOT f.use_lam AND f.taxa_adm IS NULL
                        AND (f.taxa_perfm IS NOT NULL OR f.inf_taxa_adm IS NOT NULL
                             OR f.inf_taxa_perfm IS NOT NULL) THEN
                       'cad_fi filed no administration fee rate: NULL is not a zero fee'
                   WHEN NOT f.use_ext AND NOT f.use_lam AND f.taxa_adm IS NULL AND f.taxa_perfm IS NULL
                        AND f.inf_taxa_adm IS NULL AND f.inf_taxa_perfm IS NULL THEN
                       'no disclosed fee in the Extrato, the lâmina or cad_fi: NULL is not a zero fee'
               END,
               CASE
                   WHEN f.dt_comptc IS NULL THEN
                       'no estimate: no balancete filed'
                       || CASE WHEN v_month IS NULL THEN '' ELSE ' for ' || to_char(v_month, 'YYYY-MM') END
                   WHEN f.reset_confirmed THEN
                       'estimate from the balancete accruals: this month''s accumulated fee alone, because cad_fi DT_INI_EXERC puts the fiscal-year start in this month; x 12 / NAV'
                   WHEN NOT f.has_prev THEN
                       'no estimate: no balancete for the previous month, so the month''s accrual is unknown'
                   WHEN f.reset_suspect THEN
                       'no estimate: the accumulated administration fee fell, the fund''s fiscal-year reset month, and no cad_fi DT_INI_EXERC confirms it'
                   WHEN f.adm_acc IS NULL THEN
                       'estimate from the balancete accruals; no administration fee account filed this month'
                   ELSE
                       'estimate from the balancete accruals: (previous minus current accumulated fee) x 12 / NAV, not the disclosed fee'
               END,
               -- ---- appended in v52 ----
               f.origin,
               CASE f.origin WHEN 'extrato' THEN f.x_age
                             WHEN 'lamina' THEN (CURRENT_DATE - f.lam_dt)::int END,
               f.is_zero,
               f.is_implausible,
               f.fee_raw,
               CASE WHEN f.use_ext THEN f.x_tp END,
               CASE WHEN f.use_ext THEN f.x_classe END,
               CASE WHEN f.use_ext AND f.x_tp = 'CLASSES - FIF' THEN
                        'class-level row (CVM 175): the Extrato has no subclass column, so this is the class''s fee; a fee that differs by subclass is not visible and no subclass fee is assumed'
                    WHEN f.use_ext AND f.x_tp IS NOT NULL THEN
                        'fund-level row (ICVM 555): the fee of the fund as filed'
               END,
               CASE WHEN f.use_ext THEN f.x_existe_perfm END,
               CASE WHEN f.use_ext THEN f.x_perfm END,
               CASE WHEN f.use_ext THEN f.x_param END,
               CASE WHEN f.use_ext THEN f.x_calc END,
               CASE WHEN f.use_ext THEN f.x_inf END,
               CASE WHEN f.use_ext THEN f.x_existe_ing END,
               CASE WHEN f.use_ext THEN f.x_ing_pr END,
               CASE WHEN f.use_ext THEN f.x_ing_real END,
               CASE WHEN f.use_ext THEN f.x_existe_saida END,
               CASE WHEN f.use_ext THEN f.x_saida_pr END,
               CASE WHEN f.use_ext THEN f.x_saida_real END,
               CASE WHEN f.use_ext THEN f.x_custodia END,
               CASE WHEN f.lam_dt IS NOT NULL AND f.n_desp = 1 AND NOT f.has_empty_desp THEN f.desp END,
               CASE WHEN f.lam_dt IS NOT NULL AND f.n_desp = 1 AND NOT f.has_empty_desp THEN f.desp_ini END,
               CASE WHEN f.lam_dt IS NOT NULL AND f.n_desp = 1 AND NOT f.has_empty_desp THEN f.desp_fim END,
               f.lam_dt,
               CASE
                   WHEN f.lam_dt IS NULL THEN NULL
                   WHEN f.n_desp > 1 THEN
                       'the fund''s ' || f.n_classes || ' classes declare different expense ratios: the single value is NULL'
                   WHEN f.n_desp = 0 THEN
                       'the lâmina filed no expense ratio (PR_PL_DESPESA): NULL is not a zero'
                   WHEN f.has_empty_desp THEN
                       'at least one class filed no expense ratio: NULL is not a zero'
               END,
               -- ---- appended in v55 ----
               CASE
                   WHEN f.lam_newer THEN 'lamina_newer'
                   WHEN f.use_ext AND (f.x_adm = 0 OR f.x_adm > 5) AND f.adm_min IS NOT NULL THEN 'extrato_lamina_beside'
                   WHEN f.use_ext AND (f.x_adm = 0 OR f.x_adm > 5) THEN 'extrato_to_check'
                   ELSE f.origin
               END,
               f.lam_single,
               f.adm_min,
               f.adm_max,
               f.n_classes,
               CASE WHEN f.lam_dt IS NOT NULL AND f.newest_month IS NOT NULL THEN
                    GREATEST(0, ((extract(year FROM f.newest_month) - extract(year FROM f.lam_dt)) * 12
                                 + extract(month FROM f.newest_month) - extract(month FROM f.lam_dt))::int) END,
               f.x_adm,
               f.x_dt,
               CASE WHEN f.x_adm > 0 AND f.lam_single > 0 THEN round(f.x_adm / f.lam_single, 4) END,
               CASE WHEN f.x_adm > 5 AND f.lam_single > 0 THEN
                    CASE WHEN abs(f.x_adm - 10 * f.lam_single) <= 10 * 0.005 + 0.005 THEN 10
                         WHEN abs(f.x_adm - 100 * f.lam_single) <= 100 * 0.005 + 0.005 THEN 100 END
               END,
               -- ---- appended in v56 ----
               et.ticker,
               es.s_fee,
               es.s_dt,
               es.s_source,
               CASE
                   WHEN et.ticker IS NULL THEN NULL
                   WHEN es.s_fee IS NULL THEN
                       'ETF ' || et.ticker || ' in SILO''s ETF registry: no etfsbrasil.com.br snapshot with a fee for this ticker; NULL is not a zero fee'
                   ELSE
                       'ETF ' || et.ticker || ': ''Taxa de administração total'' as printed on etfsbrasil.com.br on '
                       || to_char(es.s_dt, 'YYYY-MM-DD')
                       || ', a third-party site, not a CVM filing; returned as published, never rescaled, never in disclosed_* (CVM''s Extrato, lâmina and cad_fi carry no ETF fee)'
                       || CASE WHEN es.s_cnpj IS NOT NULL AND es.s_cnpj <> f.cnpj THEN
                               '; the site prints CNPJ ' || es.s_cnpj || ' for this ticker, SILO''s ETF registry has ' || f.cnpj
                          ELSE '' END
                       || '; etf_site_nr_cotistas and etf_site_pl are the site''s ''Número de cotistas'' and ''Patrimônio líquido'' (R$) of the same snapshot, descriptive facts, never summed'
               END,
               -- ---- appended in v57: the same snapshot row as the fee ----
               es.s_cotistas,
               es.s_pl
        FROM flag f
        LEFT JOIN etf et ON et.cnpj = f.cnpj
        LEFT JOIN etf_site es ON es.ticker = et.ticker
        ORDER BY f.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.month, g.nav, g.adm_fee_flow, g.adm_fee_pct_annual_est,
           g.perf_fee_flow, g.perf_fee_pct_annual_est, g.fiscal_reset_suspect,
           g.disclosed_taxa_adm, g.disclosed_taxa_adm_min, g.disclosed_taxa_adm_max,
           g.disclosed_taxa_perfm, g.disclosed_taxa_adm_info, g.disclosed_taxa_perfm_info,
           g.disclosed_source, g.disclosed_as_of, g.disclosed_age_months,
           g.disclosed_n_classes, g.disclosed_note, g.estimate_label,
           g.disclosed_origin, g.disclosed_age_days, g.filed_zero, g.implausible_filed,
           g.taxa_adm_filed_raw, g.extrato_tp_fundo_classe, g.extrato_classe_anbima,
           g.extrato_class_note, g.extrato_existe_taxa_perfm, g.extrato_taxa_perfm,
           g.extrato_param_taxa_perfm, g.extrato_calc_taxa_perfm, g.extrato_inf_taxa_perfm,
           g.extrato_existe_taxa_ingresso, g.extrato_taxa_ingresso_pr, g.extrato_taxa_ingresso_real,
           g.extrato_existe_taxa_saida, g.extrato_taxa_saida_pr, g.extrato_taxa_saida_real,
           g.extrato_taxa_custodia_max, g.lamina_pr_pl_despesa, g.lamina_dt_ini_despesa,
           g.lamina_dt_fim_despesa, g.lamina_as_of, g.lamina_expense_note,
           g.fee_resolution, g.lamina_taxa_adm, g.lamina_taxa_adm_min, g.lamina_taxa_adm_max,
           g.lamina_n_classes, g.lamina_age_months, g.extrato_taxa_adm_filed, g.extrato_as_of,
           g.extrato_lamina_ratio, g.extrato_scale_factor,
           g.etf_ticker, g.etf_site_taxa_adm, g.etf_site_as_of, g.etf_site_source, g.etf_site_note,
           g.etf_site_nr_cotistas, g.etf_site_pl
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'portfolio_fees')
    ORDER BY g.cnpj
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.portfolio_fees(TEXT[], DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.portfolio_fees(TEXT[], DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.portfolio_fees(TEXT[], DATE) TO silo_api;

COMMENT ON FUNCTION api.portfolio_fees(TEXT[], DATE) IS
    'Fees per fund, two kinds of number that are never mixed. DISCLOSED (disclosed_*): the fee the fund published, ONE source per fund in this order: the CVM Extrato das Informacoes (cvm_fi_extrato, newest version, one row per fund or class), else the lâmina (cvm_fi_lamina, newest reference month), else cad_fi (cvm_fund_registry taxa_adm / taxa_perfm / inf_taxa_*); disclosed_origin (extrato | lamina | cad_fi), disclosed_source, disclosed_as_of (the filing date), disclosed_age_months and disclosed_age_days say which and how old. Two reading rules on the single administration fee, % a year as filed: a filed 0 is returned as 0 with filed_zero TRUE (read it as not informed, never as a zero cost); a filed value above 5 (or below 0) is NOT returned as the fee: disclosed_taxa_adm is NULL, implausible_filed is TRUE and the value as filed is in taxa_adm_filed_raw. The stored value is never rewritten. A NULL disclosed part is not a zero fee; when the lâmina''s classes disclose different fees the single value is NULL and the min / max and disclosed_note say so. An Extrato row that exists is the source, even when its fee is 0 or above 5: it does not fall through to an OLDER source. One exception (v55): when the Extrato filed exactly 0 or above 5, the lâmina''s single fee is in (0, 5] and the lâmina is NEWER than the Extrato, the newer lâmina is the source. fee_resolution names the rule: extrato, extrato_lamina_beside (Extrato 0 or above 5, a lâmina fee beside it), extrato_to_check (the same with no lâmina fee), lamina_newer, lamina, cad_fi. The other document''s fee is returned as filed whatever the source (lamina_taxa_adm, _min, _max, lamina_n_classes, lamina_age_months; extrato_taxa_adm_filed with extrato_as_of), never rescaled and never a fee to sum; extrato_lamina_ratio is the Extrato over the lâmina when both are above 0, and extrato_scale_factor is 10 or 100 when an Extrato above 5 equals that factor times the lâmina within the two-decimal rounding of both, a flag only. The Extrato''s performance fee (extrato_taxa_perfm numeric, extrato_param_taxa_perfm, extrato_calc_taxa_perfm, extrato_inf_taxa_perfm text), entry and exit fees (extrato_existe_* flags, _pr percent and _real reais), custody fee and class note are returned as filed; the row is the class for a CVM 175 fund (no subclass column, a subclass fee is not assumed). lamina_pr_pl_despesa is the declared total expense ratio from the lâmina (with its period and lamina_as_of), whatever the fee source, never added to the administration fee. ESTIMATE (adm_fee_flow, perf_fee_flow and the _pct_annual_est columns): from the balancete accruals (cvm_fi_balancete_resumo): the fee accounts accumulate from each fund''s fiscal-year start and are filed negative, so the month''s accrual is previous minus current accumulated value (served positive = cost; a negative performance accrual is a reversed provision), annualised x 12 / NAV x 100, NAV = groups 6 + 7 + 8 of the month. In the fiscal-year reset month the accumulated fee falls: fiscal_reset_suspect is TRUE and the estimate is NULL, unless cad_fi DT_INI_EXERC puts the fiscal-year start in that month, in which case the month''s accumulated value alone is the accrual. estimate_label says on every row that the estimate is an estimate and why one is missing; it is never presented as the disclosed fee. ETFs (v56): CVM''s Extrato, lâmina and cad_fi carry no fee for an ETF, so for a CNPJ in SILO''s curated ETF registry etf_ticker names the ticker and etf_site_taxa_adm, etf_site_as_of and etf_site_source give the ''Taxa de administração total'' etfsbrasil.com.br prints (etf_market_snapshot, the newest snapshot with a fee, joined by ticker): a third-party site, not a CVM filing, never in disclosed_*, returned as published; etf_site_note says so and why a value is NULL. Since v57 etf_site_nr_cotistas and etf_site_pl (R$) are the ''Número de cotistas'' and ''Patrimônio líquido'' the same site prints in the SAME snapshot (etf_site_as_of): third-party descriptive facts, never summed, never a fee base. p_month = the balancete month (NULL = each fund''s newest). One row per distinct CNPJ; more than 200 CNPJs RAISES 22023.';


-- ---------------------------------------------------------------------------
-- portfolio_lookthrough - holdings through fund quotas, CDA blocks 1, 2, 4, 6
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.portfolio_lookthrough(
    p_cnpjs     TEXT[],              -- the roots, 14-digit CNPJs (punctuation ignored); at most 200
    p_month     DATE DEFAULT NULL,   -- the CDA month (any day of it); NULL = the last complete CDA month
    p_max_depth INT  DEFAULT 4       -- fund-quota levels to look through, 1..6
)
RETURNS TABLE (
    root_cnpj      TEXT,     -- the fund the caller asked about
    path           TEXT[],   -- root .. holder: the fund-quota chain to this row's holder
    depth          INT,      -- 0 = the root's own holdings; n = n quota levels below it
    holder_cnpj    TEXT,     -- the fund that files this position
    block          INT,      -- CDA block: 1 bonds, 2 fund quotas, 4 coded assets, 6 private credit; NULL for no_cda_filing
    asset_kind     TEXT,     -- government_bond | repo | other_block1 | fund_quota | fund_quota_unfiled | fund_quota_depth_cap | fund_quota_cycle | stock | debenture | other_block4 | private_credit | no_cda_filing
    asset_key      TEXT,     -- block 1 ISIN (else SELIC code); block 2 held CNPJ; block 4 ticker (else ISIN); block 6 CETIP code (else row_hash)
    asset_name     TEXT,     -- block 1 tp_titpub; block 2 nm_fundo_cota; block 4 ds_ativo; block 6 emissor; as filed
    isin           TEXT,
    issuer_cnpj    TEXT,     -- block 6 only, and only when PF_PJ_EMISSOR = PJ
    issuer_code    TEXT,     -- block 4: ISIN characters 3-6 (BRTAEEDBS0O9 -> TAEE); never a CNPJ
    tp_aplic       TEXT,
    tp_ativo       TEXT,
    tp_titpub      TEXT,     -- block 1: NTN-B, LFT, LTN... as filed
    indexer_code   TEXT,     -- block 6 cd_indexador_posfx as filed (DI1, IAP, PRE, OUT...); NULL elsewhere
    maturity       DATE,     -- blocks 1 and 6 dt_venc
    value_brl      NUMERIC,  -- vl_merc_pos_final as filed (block 2: summed per holder and held fund)
    weight_in_root NUMERIC,  -- share of the root's NAV through this path; NULL when a NAV on the path is unknown
    period         DATE,     -- the CDA month (first day)
    is_cycle       BOOLEAN   -- TRUE on a fund_quota_cycle row: the held fund is already on the path
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_n      INT := COALESCE(cardinality(p_cnpjs), 0);
    v_period DATE;
    v_bad    TEXT;
BEGIN
    IF v_n = 0 THEN
        RAISE EXCEPTION 'portfolio_lookthrough needs p_cnpjs, the funds'' 14-digit CNPJs (resolve names with portfolio_resolve)'
            USING ERRCODE = '22023';
    END IF;
    IF v_n > 200 THEN
        RAISE EXCEPTION
            'portfolio_lookthrough: refused, % CNPJs is more than 200 per call. SILO caps a portfolio call at 200 funds. To fix: split the set into calls of a few funds each.',
            v_n
            USING ERRCODE = '22023',
                  HINT = 'Send fewer CNPJs per call.';
    END IF;
    IF p_max_depth IS NULL OR p_max_depth < 1 OR p_max_depth > 6 THEN
        RAISE EXCEPTION 'portfolio_lookthrough: p_max_depth must be 1..6 fund-quota levels, got %', p_max_depth
            USING ERRCODE = '22023';
    END IF;
    SELECT x INTO v_bad
    FROM unnest(p_cnpjs) AS u(x)
    WHERE x IS NULL OR regexp_replace(x, '\D', '', 'g') !~ '^[0-9]{1,14}$'
    LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'portfolio_lookthrough: every p_cnpjs entry must be a fund''s CNPJ (up to 14 digits, punctuation ignored); got %',
            COALESCE(v_bad, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    IF p_month IS NOT NULL THEN
        v_period := date_trunc('month', p_month)::date;
    ELSE
        -- The /holdings rule (holdings_monthly.sql): the newest month whose
        -- block-2 filing count reaches 90% of the median of the 12 before it.
        WITH tot AS (
            SELECT h.period, h.n_funds
            FROM public.mv_fund_holdings_monthly h
            WHERE h.kind = 'quota' AND h.key IS NULL
        )
        SELECT max(m.period) INTO v_period
        FROM tot m
        WHERE m.n_funds >= 0.9 * (
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY p.n_funds)
            FROM tot p
            WHERE p.period < m.period
              AND p.period >= m.period - INTERVAL '12 months'
        );
        IF v_period IS NULL THEN
            RAISE EXCEPTION
                'portfolio_lookthrough: no complete CDA month to default to (mv_fund_holdings_monthly holds fewer than two months of block 2); pass p_month'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    RETURN QUERY
    WITH RECURSIVE roots AS (
        SELECT DISTINCT lpad(regexp_replace(x, '\D', '', 'g'), 14, '0') AS cnpj
        FROM unnest(p_cnpjs) AS u(x)
    ),
    -- Nodes: the root at depth 0, then every held fund down the block-2 edges.
    -- held is the node's CNPJ; w its weight in the root (product of value /
    -- holder NAV down the path); CYCLE stops at a CNPJ already on the path.
    tree (root, held, depth, path, w) AS (
        SELECT r.cnpj, r.cnpj, 0, ARRAY[r.cnpj], 1::numeric
        FROM roots r
        UNION ALL
        SELECT t.root, e.cnpj_cota, t.depth + 1, t.path || e.cnpj_cota,
               t.w * e.v / NULLIF(nav.v, 0)
        FROM tree t
        CROSS JOIN LATERAL (
            SELECT c.cnpj_cota, sum(c.vl_merc_pos_final) AS v
            FROM public.cvm_fi_cda_cotas c
            WHERE c.cnpj = t.held AND c.period = v_period
            GROUP BY c.cnpj_cota
        ) e
        LEFT JOIN LATERAL (
            SELECT f.vl_patrim_liq AS v
            FROM public.fact_fund_monthly f
            WHERE f.cnpj = t.held AND f.period = v_period AND f.entity_type = 'fi'
        ) nav ON TRUE
        WHERE t.depth < p_max_depth
    ) CYCLE held SET is_cycle USING cycle_path,
    nodes AS (
        -- Columns named one by one: t.* does not expand the CYCLE columns.
        SELECT t.root, t.held, t.depth, t.path, t.w
        FROM tree t
        WHERE NOT t.is_cycle
    ),
    node_nav AS (
        SELECT n.root, n.held, n.depth, n.path, n.w, f.vl_patrim_liq AS nav,
               -- Filed = any position in blocks 1, 2, 4 or 6 at this month, each
               -- an index probe on the (cnpj, period, ...) unique index.
               (EXISTS (SELECT 1 FROM public.cvm_fi_cda x WHERE x.cnpj = n.held AND x.period = v_period)
                OR EXISTS (SELECT 1 FROM public.cvm_fi_cda_cotas x WHERE x.cnpj = n.held AND x.period = v_period)
                OR EXISTS (SELECT 1 FROM public.cvm_fi_cda_acoes x WHERE x.cnpj = n.held AND x.period = v_period)
                OR EXISTS (SELECT 1 FROM public.cvm_fi_cda_debentures x WHERE x.cnpj = n.held AND x.period = v_period)) AS filed
        FROM nodes n
        LEFT JOIN public.fact_fund_monthly f
               ON f.cnpj = n.held AND f.period = v_period AND f.entity_type = 'fi'
    ),
    -- Block 1: government bonds; repo apart.
    b1 AS (
        SELECT n.root, n.path, n.depth, n.held AS holder, 1 AS block,
               CASE x.tp_aplic
                   WHEN 'Títulos Públicos' THEN 'government_bond'
                   WHEN 'Operações Compromissadas' THEN 'repo'
                   ELSE 'other_block1'
               END AS asset_kind,
               COALESCE(x.cd_isin, x.cd_selic) AS asset_key, x.tp_titpub AS asset_name,
               x.cd_isin AS isin, NULL::text AS issuer_cnpj, NULL::text AS issuer_code,
               x.tp_aplic, x.tp_ativo, x.tp_titpub, NULL::text AS indexer_code,
               x.dt_venc AS maturity, x.vl_merc_pos_final::numeric AS value_brl,
               n.w * x.vl_merc_pos_final / NULLIF(n.nav, 0) AS weight, FALSE AS is_cycle
        FROM node_nav n
        JOIN public.cvm_fi_cda x ON x.cnpj = n.held AND x.period = v_period
    ),
    -- Block 2: one row per holder and held fund, with what became of it.
    b2 AS (
        SELECT n.root, n.path, n.depth, n.held AS holder, 2 AS block,
               CASE
                   WHEN e.cnpj_cota = ANY (n.path) THEN 'fund_quota_cycle'
                   WHEN n.depth >= p_max_depth THEN 'fund_quota_depth_cap'
                   WHEN NOT EXISTS (SELECT 1 FROM node_nav c
                                    WHERE c.root = n.root AND c.path = n.path || e.cnpj_cota
                                      AND c.filed) THEN 'fund_quota_unfiled'
                   ELSE 'fund_quota'
               END AS asset_kind,
               e.cnpj_cota AS asset_key, e.nm_fundo_cota AS asset_name,
               NULL::text AS isin, NULL::text AS issuer_cnpj, NULL::text AS issuer_code,
               e.tp_aplic, e.tp_ativo, NULL::text AS tp_titpub, NULL::text AS indexer_code,
               NULL::date AS maturity, e.v AS value_brl,
               n.w * e.v / NULLIF(n.nav, 0) AS weight,
               (e.cnpj_cota = ANY (n.path)) AS is_cycle
        FROM node_nav n
        CROSS JOIN LATERAL (
            SELECT c.cnpj_cota, sum(c.vl_merc_pos_final) AS v,
                   min(c.nm_fundo_cota) AS nm_fundo_cota,
                   string_agg(DISTINCT c.tp_aplic, ' | ' ORDER BY c.tp_aplic) AS tp_aplic,
                   string_agg(DISTINCT c.tp_ativo, ' | ' ORDER BY c.tp_ativo) AS tp_ativo
            FROM public.cvm_fi_cda_cotas c
            WHERE c.cnpj = n.held AND c.period = v_period
            GROUP BY c.cnpj_cota
        ) e
    ),
    -- Block 4: coded assets.
    b4 AS (
        SELECT n.root, n.path, n.depth, n.held AS holder, 4 AS block,
               CASE
                   WHEN x.tp_aplic IN ('Ações',
                                       'Ações e outros TVM cedidos em empréstimo',
                                       'Certificado ou recibo de depósito de valores mobiliários')
                       THEN 'stock'
                   WHEN x.tp_aplic = 'Debêntures' THEN 'debenture'
                   ELSE 'other_block4'
               END AS asset_kind,
               COALESCE(x.cd_ativo, x.cd_isin) AS asset_key, x.ds_ativo AS asset_name,
               x.cd_isin AS isin, NULL::text AS issuer_cnpj,
               CASE WHEN x.cd_isin ~ '^BR[A-Z0-9]{10}$' THEN substring(x.cd_isin FROM 3 FOR 4) END AS issuer_code,
               x.tp_aplic, x.tp_ativo, NULL::text AS tp_titpub, NULL::text AS indexer_code,
               NULL::date AS maturity, x.vl_merc_pos_final::numeric AS value_brl,
               n.w * x.vl_merc_pos_final / NULLIF(n.nav, 0) AS weight, FALSE AS is_cycle
        FROM node_nav n
        JOIN public.cvm_fi_cda_acoes x ON x.cnpj = n.held AND x.period = v_period
    ),
    -- Block 6: private credit with the issuer's own CNPJ.
    b6 AS (
        SELECT n.root, n.path, n.depth, n.held AS holder, 6 AS block,
               'private_credit'::text AS asset_kind,
               COALESCE(x.titulo_cetip, x.row_hash) AS asset_key, x.emissor AS asset_name,
               NULL::text AS isin,
               CASE WHEN upper(btrim(x.pf_pj_emissor)) = 'PJ' THEN x.cpf_cnpj_emissor END AS issuer_cnpj,
               NULL::text AS issuer_code,
               x.tp_aplic, x.tp_ativo, NULL::text AS tp_titpub,
               x.cd_indexador_posfx AS indexer_code,
               x.dt_venc AS maturity, x.vl_merc_pos_final::numeric AS value_brl,
               n.w * x.vl_merc_pos_final / NULLIF(n.nav, 0) AS weight, FALSE AS is_cycle
        FROM node_nav n
        JOIN public.cvm_fi_cda_debentures x ON x.cnpj = n.held AND x.period = v_period
    ),
    -- A root with no CDA filing at all still gets a row, so it is not lost.
    unfiled_roots AS (
        SELECT n.root, n.path, 0 AS depth, n.held AS holder, NULL::int AS block,
               'no_cda_filing'::text AS asset_kind, NULL::text AS asset_key,
               NULL::text AS asset_name, NULL::text AS isin, NULL::text AS issuer_cnpj,
               NULL::text AS issuer_code, NULL::text AS tp_aplic, NULL::text AS tp_ativo,
               NULL::text AS tp_titpub, NULL::text AS indexer_code, NULL::date AS maturity,
               NULL::numeric AS value_brl, NULL::numeric AS weight, FALSE AS is_cycle
        FROM node_nav n
        WHERE n.depth = 0 AND NOT n.filed
    ),
    allrows AS (
        SELECT * FROM b1
        UNION ALL SELECT * FROM b2
        UNION ALL SELECT * FROM b4
        UNION ALL SELECT * FROM b6
        UNION ALL SELECT * FROM unfiled_roots
    ),
    page (root_cnpj, path, depth, holder_cnpj, block, asset_kind, asset_key,
          asset_name, isin, issuer_cnpj, issuer_code, tp_aplic, tp_ativo,
          tp_titpub, indexer_code, maturity, value_brl, weight_in_root,
          period, is_cycle) AS (
        SELECT a.root, a.path, a.depth, a.holder, a.block, a.asset_kind, a.asset_key,
               a.asset_name, a.isin, a.issuer_cnpj, a.issuer_code, a.tp_aplic, a.tp_ativo,
               a.tp_titpub, a.indexer_code, a.maturity, a.value_brl, round(a.weight, 10),
               v_period, a.is_cycle
        FROM allrows a
        ORDER BY a.root, a.depth, a.path, a.block NULLS FIRST, a.value_brl DESC NULLS LAST,
                 a.asset_key
        LIMIT 1001
    )
    SELECT g.root_cnpj, g.path, g.depth, g.holder_cnpj, g.block, g.asset_kind, g.asset_key,
           g.asset_name, g.isin, g.issuer_cnpj, g.issuer_code, g.tp_aplic, g.tp_ativo,
           g.tp_titpub, g.indexer_code, g.maturity, g.value_brl, g.weight_in_root,
           g.period, g.is_cycle
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'portfolio_lookthrough')
    ORDER BY g.root_cnpj, g.depth, g.path, g.block NULLS FIRST, g.value_brl DESC NULLS LAST,
             g.asset_key
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.portfolio_lookthrough(TEXT[], DATE, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.portfolio_lookthrough(TEXT[], DATE, INT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.portfolio_lookthrough(TEXT[], DATE, INT) TO silo_api;

COMMENT ON FUNCTION api.portfolio_lookthrough(TEXT[], DATE, INT) IS
    'What a set of funds holds, looked through their fund quotas. One CDA month (p_month, or by default the last complete one: the newest month whose block-2 filing count reaches 90% of the median of the 12 before it, the /holdings rule). From each root, CDA block 2 (fund quotas) is followed recursively, cycle-guarded and capped at p_max_depth levels (1..6, default 4); every fund on the way, root included, lists its own holdings from block 1 (government_bond; repo collateral served apart as repo), block 2 (fund_quota when looked through, else fund_quota_unfiled / fund_quota_depth_cap / fund_quota_cycle), block 4 (stock, debenture with issuer_code = ISIN chars 3-6, other_block4) and block 6 (private_credit with the issuer''s CNPJ when it is a PJ and the indexer as filed). weight_in_root = value / holder NAV times the weights down the path, NAV = fact_fund_monthly.vl_patrim_liq of the same month (not the CDA blocks'' total: blocks 3, 5, 7, 8 are not ingested); NULL when a NAV on the path is unknown. A fund reached by two paths appears once per path; sum weight_in_root over every row but fund_quota for the exposure. A root with no CDA that month returns one no_cda_filing row. More than 200 CNPJs or more than 1000 rows RAISES 22023 (never trimmed): send fewer funds per call or lower p_max_depth.';

-- ---------------------------------------------------------------------------
-- portfolio_movement - is a fund's month unusual for its own class?
-- ---------------------------------------------------------------------------
-- "Movimento incomum" (map #510, owner decisions of 2026-10-03). For each fund
-- and ONE month, the fund's monthly QUOTA RETURN is set against the
-- distribution of the same return over the funds of its own ANBIMA class:
--
--   own_value_pct  = (vl_quota(month) / vl_quota(previous month) - 1) x 100,
--                    from fact_fund_monthly (FI, month-end quota of the one
--                    stable subclass the matview follows, quota_subclass_id):
--                    the same month-end quotas Phase 0 counted (note, query 7).
--                    NAV is NOT used: a NAV change is mostly flows, not movement.
--                    A fund with no positive quota in both months, or whose
--                    quota subclass changed, has no return and is not evaluated.
--   class          = the ANBIMA class AS FILED in the CVM Extrato das
--                    Informacoes (vw_fi_extrato_latest.classe_anbima), the label
--                    CVM publishes, e.g. 'AÇÕES - ATIVO - LIVRE'. The peer group
--                    is that whole label (68 groups on 2026-09). `class` and
--                    `subclass` split the same label at its first ' - ' for
--                    display only ('AÇÕES' | 'ATIVO - LIVRE'; a label with no
--                    ' - ' has a NULL subclass); nothing is parsed or inferred
--                    from a fund name. The class is the Extrato's NEWEST filing,
--                    not the class on the month's date (class_as_of says when).
--                    The Extrato covers about 84% of the active FI funds: a fund
--                    outside it, or with no classe_anbima, is not evaluated.
--   peers          = every FI fund of the class with a return that month (the
--                    fund itself included), read from the whole warehouse and
--                    not from p_cnpjs: n_peers.
--   class_mean_pct, class_sd_pct = mean and sample standard deviation of the
--                    peers' returns WINSORIZED at the class's own 1st and 99th
--                    percentile that month (class_p01_pct, class_p99_pct): a
--                    value beyond a bound is replaced by the bound. The fund's
--                    own value is NOT winsorized when it is compared.
--   z              = (own_value_pct - class_mean_pct) / class_sd_pct.
--   level          = 'forte' when |z| > 3, 'atencao' when |z| > 2, else
--                    'normal' (strictly greater: exactly 2 is normal, exactly 3
--                    is atencao); decided on the unrounded z by
--                    public.portfolio_movement_level. investigator_trigger is
--                    TRUE exactly when level = 'forte'.
--   nao_avaliado   = not evaluated, never skipped and never zero: reason says
--                    why. Fewer than min_peers (30) peers; a class with a zero
--                    standard deviation; no class; no return; a month that is
--                    not complete (mv_period_completeness). There is no fallback
--                    to a wider class, and no fund-name guess.
-- Measured on production 2026-10-03 (monthly FI funds with a return and a class
-- of at least 30 peers; 20,869 of the 25,113 fund-months with a return in 2026-09,
-- the rest having no class or too few peers): |z| > 2 flags 5.2% to 5.7% of
-- fund-months and |z| > 3 2.4% to 2.9% over the six months 2025-12, 2026-03,
-- 2026-04, 2026-06, 2026-08 and 2026-09 (5.6% and 2.7% in 2026-09). Nothing here
-- is a forecast, a verdict or
-- a recommendation: it states a number, a class, a sample size and a month.
-- p_month = any day of the month; NULL = the last COMPLETE FI month
-- (latest_complete_period('fi'), the serving rule). At most 200 CNPJs.
-- Reads: fact_fund_monthly (two month probes by the CNPJ key), the Extrato
-- view, and, for the peers, the two months of the funds of the requested
-- classes. The anon role's 3 s statement_timeout is the budget.

-- The thresholds in one place. IMMUTABLE and internal (no client grant): the
-- boundary is tested by calling it with exactly 2 and exactly 3.
CREATE OR REPLACE FUNCTION public.portfolio_movement_level(p_z NUMERIC)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $fn$
    SELECT CASE
        WHEN p_z IS NULL THEN NULL
        WHEN abs(p_z) > 3 THEN 'forte'
        WHEN abs(p_z) > 2 THEN 'atencao'
        ELSE 'normal'
    END
$fn$;

REVOKE ALL ON FUNCTION public.portfolio_movement_level(NUMERIC) FROM PUBLIC;

COMMENT ON FUNCTION public.portfolio_movement_level(NUMERIC) IS
    'Internal (31_api_portfolio.sql). The movement thresholds: forte when |z| > 3, atencao when |z| > 2, else normal; strictly greater, so exactly 2 is normal and exactly 3 is atencao. NULL in, NULL out.';

CREATE OR REPLACE FUNCTION api.portfolio_movement(
    p_cnpjs TEXT[],              -- the funds, 14-digit CNPJs (punctuation ignored); at most 200
    p_month DATE DEFAULT NULL    -- any day of the month to judge; NULL = the last complete FI month
)
RETURNS TABLE (
    cnpj                 TEXT,
    fund_name            TEXT,     -- the registry name; NULL = the CNPJ is not in the registry
    month                DATE,     -- first day of the judged month
    class                TEXT,     -- the first segment of the ANBIMA class as filed ('AÇÕES'); NULL = no class
    subclass             TEXT,     -- the rest of the label ('ATIVO - LIVRE'); NULL = the label has no ' - ' or no class
    class_as_filed       TEXT,     -- the whole ANBIMA class as filed: the peer group
    class_as_of          DATE,     -- DT_COMPTC of the Extrato version the class comes from
    n_peers              INT,      -- FI funds of the class with a return that month, the fund included; NULL when no class
    own_value_pct        NUMERIC,  -- the fund's quota return in the month, % (not winsorized); NULL = none computable
    class_mean_pct       NUMERIC,  -- mean of the class's winsorized returns, %
    class_sd_pct         NUMERIC,  -- sample standard deviation of the class's winsorized returns, %
    class_p01_pct        NUMERIC,  -- the 1st percentile the returns were winsorized at, %
    class_p99_pct        NUMERIC,  -- the 99th percentile, %
    z                    NUMERIC,  -- (own - mean) / sd, 4 decimals; level is decided on the unrounded value
    level                TEXT,     -- normal | atencao (|z| > 2) | forte (|z| > 3) | nao_avaliado
    investigator_trigger BOOLEAN,  -- TRUE exactly when level = 'forte'
    min_peers            INT,      -- the smallest class evaluated (30)
    reason               TEXT      -- Portuguese: why the fund is nao_avaliado; for an evaluated fund, what was compared
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_n        INT  := COALESCE(cardinality(p_cnpjs), 0);
    v_min      INT  := 30;
    v_bad      TEXT;
    v_ids      TEXT[];
    v_cur      DATE;
    v_prev     DATE;
    v_complete BOOLEAN;
BEGIN
    IF v_n = 0 THEN
        RAISE EXCEPTION 'portfolio_movement needs p_cnpjs, the funds'' 14-digit CNPJs (resolve names with portfolio_resolve)'
            USING ERRCODE = '22023';
    END IF;
    IF v_n > 200 THEN
        RAISE EXCEPTION
            'portfolio_movement: refused, % CNPJs is more than 200 per call. SILO caps a portfolio call at 200 funds. To fix: split the set into calls of at most 200.',
            v_n
            USING ERRCODE = '22023',
                  HINT = 'Send at most 200 CNPJs per call.';
    END IF;
    SELECT x INTO v_bad
    FROM unnest(p_cnpjs) AS u(x)
    WHERE x IS NULL OR regexp_replace(x, '\D', '', 'g') !~ '^[0-9]{1,14}$'
    LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'portfolio_movement: every p_cnpjs entry must be a fund''s CNPJ (up to 14 digits, punctuation ignored); got %',
            COALESCE(v_bad, 'NULL')
            USING ERRCODE = '22023';
    END IF;

    SELECT array_agg(DISTINCT lpad(regexp_replace(x, '\D', '', 'g'), 14, '0'))
      INTO v_ids
    FROM unnest(p_cnpjs) AS u(x);

    v_cur  := date_trunc('month', COALESCE(p_month, public.latest_complete_period('fi')))::date;
    v_prev := (v_cur - INTERVAL '1 month')::date;
    -- A month that is still running, or that fewer than 80% of the funds have
    -- filed, has partial peers and a quota that is not a month-end one.
    SELECT COALESCE(bool_or(pc.is_complete), FALSE) INTO v_complete
    FROM public.mv_period_completeness pc
    WHERE pc.entity_type = 'fi' AND pc.period = v_cur;

    RETURN QUERY
    WITH ids AS (
        SELECT unnest(v_ids) AS cnpj
    ),
    reg AS (
        SELECT r.cnpj,
               COALESCE(min(r.fund_name) FILTER (WHERE r.entity_type = 'fi'), min(r.fund_name)) AS fund_name,
               string_agg(DISTINCT r.entity_type, ',') AS types
        FROM public.cvm_fund_registry r
        WHERE r.cnpj = ANY (v_ids)
        GROUP BY r.cnpj
    ),
    etf AS (
        SELECT DISTINCT e.cnpj FROM public.cvm_etf_registry e WHERE e.cnpj = ANY (v_ids)
    ),
    -- The class of each requested fund: the Extrato's newest filing, as filed.
    ext AS (
        SELECT x.cnpj, NULLIF(btrim(x.classe_anbima), '') AS cls, x.dt_comptc
        FROM public.vw_fi_extrato_latest x
        WHERE x.cnpj = ANY (v_ids)
    ),
    -- The funds' own two month-end quotas (the matview's one stable subclass).
    own AS (
        SELECT i.cnpj,
               (c.cnpj IS NOT NULL) AS has_cur,
               (p.cnpj IS NOT NULL) AS has_prev,
               c.vl_quota AS q1, p.vl_quota AS q0,
               (c.quota_subclass_id IS NOT DISTINCT FROM p.quota_subclass_id) AS same_sub
        FROM ids i
        LEFT JOIN public.fact_fund_monthly c
               ON c.cnpj = i.cnpj AND c.entity_type = 'fi' AND c.period = v_cur
        LEFT JOIN public.fact_fund_monthly p
               ON p.cnpj = i.cnpj AND p.entity_type = 'fi' AND p.period = v_prev
    ),
    -- The peers: every FI fund of the requested classes with a return in the month.
    peers AS (
        SELECT NULLIF(btrim(x.classe_anbima), '') AS cls,
               (c.vl_quota / p.vl_quota - 1) * 100 AS ret
        FROM public.vw_fi_extrato_latest x
        JOIN public.fact_fund_monthly c
          ON c.cnpj = x.cnpj AND c.entity_type = 'fi' AND c.period = v_cur AND c.vl_quota > 0
        JOIN public.fact_fund_monthly p
          ON p.cnpj = x.cnpj AND p.entity_type = 'fi' AND p.period = v_prev AND p.vl_quota > 0
         AND p.quota_subclass_id IS NOT DISTINCT FROM c.quota_subclass_id
        WHERE v_complete
          AND NULLIF(btrim(x.classe_anbima), '') IN (SELECT e.cls FROM ext e WHERE e.cls IS NOT NULL)
    ),
    bounds AS (
        SELECT q.cls, count(*)::int AS n,
               percentile_cont(0.01) WITHIN GROUP (ORDER BY q.ret)::numeric AS p01,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY q.ret)::numeric AS p99
        FROM peers q
        GROUP BY q.cls
    ),
    stats AS (
        SELECT b.cls, b.n, b.p01, b.p99,
               avg(least(greatest(q.ret, b.p01), b.p99)) AS mean,
               stddev_samp(least(greatest(q.ret, b.p01), b.p99)) AS sd
        FROM peers q
        JOIN bounds b ON b.cls = q.cls
        GROUP BY b.cls, b.n, b.p01, b.p99
    ),
    j AS (
        SELECT i.cnpj, g.fund_name, g.types, (et.cnpj IS NOT NULL) AS is_etf,
               o.has_cur, o.has_prev, o.q1, o.q0, o.same_sub,
               (x.cnpj IS NOT NULL) AS in_ext, x.cls, x.dt_comptc AS ext_dt,
               CASE WHEN o.q1 > 0 AND o.q0 > 0 AND o.same_sub
                    THEN (o.q1 / o.q0 - 1) * 100 END AS own_ret,
               s.n, s.p01, s.p99, s.mean, s.sd
        FROM ids i
        LEFT JOIN reg g  ON g.cnpj = i.cnpj
        LEFT JOIN etf et ON et.cnpj = i.cnpj
        LEFT JOIN own o  ON o.cnpj = i.cnpj
        LEFT JOIN ext x  ON x.cnpj = i.cnpj
        LEFT JOIN stats s ON s.cls = x.cls
    ),
    scored AS (
        SELECT j.*,
               CASE WHEN j.own_ret IS NOT NULL AND j.n >= v_min AND j.sd > 0 AND v_complete
                    THEN (j.own_ret - j.mean) / j.sd END AS zz
        FROM j
    ),
    page AS (
        SELECT d.cnpj, d.fund_name, v_cur AS month,
               CASE WHEN d.cls IS NOT NULL THEN split_part(d.cls, ' - ', 1) END AS class,
               CASE WHEN d.cls LIKE '% - %'
                    THEN NULLIF(btrim(substr(d.cls, strpos(d.cls, ' - ') + 3)), '') END AS subclass,
               d.cls AS class_as_filed,
               CASE WHEN d.cls IS NOT NULL THEN d.ext_dt END AS class_as_of,
               CASE WHEN d.cls IS NOT NULL AND v_complete THEN COALESCE(d.n, 0) END AS n_peers,
               round(d.own_ret, 6) AS own_value_pct,
               CASE WHEN d.n >= v_min THEN round(d.mean, 6) END AS class_mean_pct,
               CASE WHEN d.n >= v_min THEN round(d.sd, 6) END AS class_sd_pct,
               CASE WHEN d.n >= v_min THEN round(d.p01, 6) END AS class_p01_pct,
               CASE WHEN d.n >= v_min THEN round(d.p99, 6) END AS class_p99_pct,
               round(d.zz, 4) AS z,
               COALESCE(public.portfolio_movement_level(d.zz), 'nao_avaliado') AS level,
               COALESCE(public.portfolio_movement_level(d.zz) = 'forte', FALSE) AS investigator_trigger,
               v_min AS min_peers,
               CASE
                   WHEN NOT v_complete THEN
                       'mês ' || to_char(v_cur, 'YYYY-MM') || ' incompleto: o mês não terminou ou menos de 80% dos fundos FI já informaram; a comparação com a classe só vale para mês completo'
                   WHEN NOT d.has_cur AND d.is_etf THEN
                       'ETF: fora do universo mensal de fundos FI (o SILO o separa dos fundos); sem retorno de cota mensal comparável'
                   WHEN NOT d.has_cur AND d.types IS NOT NULL AND NOT ('fi' = ANY (string_to_array(d.types, ','))) THEN
                       'não é fundo FI com cota diária no SILO (' || d.types || '); sem retorno de cota mensal'
                   WHEN NOT d.has_cur AND d.types IS NULL THEN
                       'CNPJ não encontrado no cadastro de fundos do SILO'
                   WHEN NOT d.has_cur THEN
                       'sem informe diário do fundo em ' || to_char(v_cur, 'YYYY-MM')
                   WHEN d.q1 IS NULL OR d.q1 <= 0 THEN
                       'cota do mês ' || to_char(v_cur, 'YYYY-MM') || ' ausente ou não positiva'
                   WHEN NOT d.has_prev OR d.q0 IS NULL OR d.q0 <= 0 THEN
                       'sem cota no mês anterior (' || to_char(v_prev, 'YYYY-MM') || '); sem retorno mensal'
                   WHEN NOT d.same_sub THEN
                       'a subclasse que fornece a cota mudou entre ' || to_char(v_prev, 'YYYY-MM') || ' e ' || to_char(v_cur, 'YYYY-MM') || '; sem retorno comparável'
                   WHEN NOT d.in_ext THEN
                       'fundo fora do Extrato da CVM: sem classe ANBIMA informada'
                   WHEN d.cls IS NULL THEN
                       'classe ANBIMA não informada no Extrato da CVM'
                   WHEN COALESCE(d.n, 0) < v_min THEN
                       'apenas ' || COALESCE(d.n, 0) || ' fundos da classe ' || d.cls || ' têm retorno em ' || to_char(v_cur, 'YYYY-MM') || '; mínimo ' || v_min || ' para comparar'
                   WHEN d.sd IS NULL OR d.sd = 0 THEN
                       'desvio padrão da classe ' || d.cls || ' é zero em ' || to_char(v_cur, 'YYYY-MM') || '; sem escala para comparar'
                   ELSE
                       'retorno de cota de ' || to_char(v_cur, 'YYYY-MM') || ' comparado com ' || d.n || ' fundos da classe ' || d.cls
                       || ' (média e desvio padrão winsorizados no 1º e 99º percentil)'
               END AS reason
        FROM scored d
        ORDER BY d.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.month, g.class, g.subclass, g.class_as_filed, g.class_as_of,
           g.n_peers, g.own_value_pct, g.class_mean_pct, g.class_sd_pct, g.class_p01_pct,
           g.class_p99_pct, g.z, g.level, g.investigator_trigger, g.min_peers, g.reason
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'portfolio_movement')
    ORDER BY g.cnpj
    LIMIT 1000;
END;
$fn$;

REVOKE ALL ON FUNCTION api.portfolio_movement(TEXT[], DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.portfolio_movement(TEXT[], DATE) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION api.portfolio_movement(TEXT[], DATE) TO silo_api;

COMMENT ON FUNCTION api.portfolio_movement(TEXT[], DATE) IS
    'Is a fund''s month unusual for its own class (movimento incomum). Per CNPJ, for one month (p_month, or the last complete FI month): the fund''s monthly QUOTA RETURN, own_value_pct = (month-end vl_quota / previous month''s - 1) x 100 from fact_fund_monthly (the one stable quota subclass; a NAV change is not used), set against the same return over every FI fund of its ANBIMA class AS FILED in the CVM Extrato (class_as_filed, the newest Extrato filing, not the class on the month''s date; class and subclass split that label at its first '' - '' for display). class_mean_pct and class_sd_pct are the mean and sample standard deviation of the peers'' returns winsorized at the class''s own 1st and 99th percentile that month (class_p01_pct, class_p99_pct); the fund''s own value is not winsorized. z = (own - mean) / sd. level: forte when |z| > 3 (investigator_trigger TRUE), atencao when |z| > 2, normal otherwise (strictly greater: exactly 2 is normal); nao_avaliado with a Portuguese reason when the class has fewer than min_peers (30) peers with a return, its standard deviation is 0, the fund has no class (outside the Extrato, or no classe_anbima), no return (no quota in both months, a quota subclass change), is an ETF, FIDC, FII, FIP or FIAGRO, or the month is not complete; never skipped and never a zero. No fallback to a wider class. Measured on production 2026-10-03 over monthly FI funds in classes of 30 or more: |z| > 2 flags 5.2% to 5.7% of fund-months and |z| > 3 2.4% to 2.9% over six months from 2025-12 to 2026-09 (5.6% and 2.7% in 2026-09). It states a number, a class, a sample size and a month: not a forecast, a verdict or a recommendation. One row per distinct CNPJ; more than 200 CNPJs RAISES 22023.';

COMMIT;
