-- =============================================================================
-- 31_api_portfolio.sql
-- The portfolio-diagnosis engine's three set-based reads, served through schema
-- `api` (catalog v51; map #510, research note
-- docs/reference/research/portfolio-diagnosis-phase0.md §2, §4, §8 slice 2-3).
--
--   api.portfolio_resolve      statement lines (names, optional CNPJs, quotas)
--                              -> candidate funds, scored, with an ambiguity flag.
--   api.portfolio_fees         per CNPJ: the fee ESTIMATED from the balancete
--                              accruals, next to the fee the fund DISCLOSED.
--   api.portfolio_lookthrough  per CNPJ: what the fund holds through its fund
--                              quotas (CDA block 2, recursively), down to the
--                              assets of CDA blocks 1, 4 and 6.
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
--   * DISCLOSED (disclosed_*): the fee the fund published. From the lâmina
--     (cvm_fi_lamina through vw_fi_lamina_latest, newest reference month, slice
--     A) when it gives a fee, else from cad_fi (cvm_fund_registry taxa_adm,
--     taxa_perfm, inf_taxa_adm, inf_taxa_perfm; migration 64). ONE source per
--     fund, named in disclosed_source with its date (disclosed_as_of; the
--     lâmina also gives disclosed_age_months). A part the source did not file is
--     NULL, never a zero fee; classes that disclose different fees give a NULL
--     single value, the min and max, and a note. The view is read dynamically
--     and by key name, so the file applies before the lâmina exists (then every
--     lâmina column is NULL and cad_fi is the source).
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
    match_kind     TEXT,     -- cnpj | exact_current | exact_history | trigram
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
    -- 2. An exact normalised name, anywhere in the history.
    exact AS (
        SELECT l.line_no, h.cnpj,
               CASE WHEN bool_or(h.is_current) THEN 'exact_current' ELSE 'exact_history' END AS kind,
               min(h.name) AS matched_name, max(h.last_period) AS matched_period,
               1.0::numeric AS sim
        FROM lines l
        JOIN public.mv_fund_name_history h ON h.name_norm = l.nn
        WHERE l.in_cnpj IS NULL AND l.nn IS NOT NULL
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
        UNION ALL SELECT * FROM exact
        UNION ALL SELECT * FROM fuzzy_top
    ),
    scored AS (
        SELECT c.line_no, c.cnpj, c.kind, c.matched_name, c.matched_period, c.sim,
               cur.name AS candidate_name,
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
                   WHEN r1.kind = 'cnpj' OR r1.n_cand = 1 THEN FALSE
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
    'Statement lines to candidate funds. One row per line and candidate (up to 5), ranked: a CNPJ the line carries wins (match_kind cnpj); else an exact match on any name the fund ever filed, case, accents and whitespace ignored (exact_current: the registry name or the newest CDA name; exact_history: a former name, matched_period = the last CDA month it was filed under); else trigram over the whole name history (CDA DENOM_SOCIAL since 2005 plus the registry), similarity = greatest(similarity, word_similarity), so an abbreviation scores high. With p_quotas and p_quota_dates the candidate''s cvm_fi_diario quota on that exact date is compared, and one within 0.5% ranks first: that is how the XP Bancos master and FIC (same words, quotas 1.952607 and 1.542011 on 2026-09-30) are told apart. ambiguous is TRUE on every row of a line whose top two candidates score within 0.05 and the quota does not separate them: SILO never picks silently, the caller decides. Arrays are parallel, one entry per line. More than 200 lines RAISES 22023; the result is at most one 1000-row page.';

-- ---------------------------------------------------------------------------
-- portfolio_fees - the disclosed fee, and a separate estimate from the balancete
-- ---------------------------------------------------------------------------
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
    disclosed_taxa_adm       NUMERIC,  -- DISCLOSED administration fee, % a year as published; NULL = not disclosed (never zero)
    disclosed_taxa_adm_min   NUMERIC,  -- lowest administration fee disclosed across the fund's classes (lâmina taxa_adm_min, else taxa_adm)
    disclosed_taxa_adm_max   NUMERIC,  -- highest administration fee disclosed across the fund's classes
    disclosed_taxa_perfm     TEXT,     -- DISCLOSED performance fee as published (text in the lâmina); NULL = not disclosed
    disclosed_taxa_adm_info  TEXT,     -- cad_fi INF_TAXA_ADM, free text, as published (cad_fi source only)
    disclosed_taxa_perfm_info TEXT,    -- cad_fi INF_TAXA_PERFM, free text, as published (cad_fi source only)
    disclosed_source         TEXT,     -- cvm_fi_lamina | cvm_fund_registry (cad_fi); NULL = nothing disclosed in either
    disclosed_as_of          DATE,     -- lâmina: the reference month (dt_comptc); cad_fi: the day SILO read the row (UTC-3)
    disclosed_age_months     INT,      -- months from disclosed_as_of to the end of the newest month SILO holds; NULL for cad_fi
    disclosed_n_classes      INT,      -- lâmina classes/subclasses at that reference month; NULL for cad_fi
    disclosed_note           TEXT,     -- why a disclosed number is NULL or a range (classes differ), else NULL
    estimate_label           TEXT      -- says the estimate is an estimate, and why one is missing
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
    -- slice A, branch demo/lamina) is read dynamically and by key name, so this
    -- function applies on a database that does not hold the view yet - every
    -- lâmina column is then NULL and the fee falls back to cad_fi.
    IF to_regclass('public.vw_fi_lamina_latest') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(jsonb_agg(to_jsonb(v)), ''[]''::jsonb) '
             || 'FROM public.vw_fi_lamina_latest v WHERE v.cnpj = ANY ($1)'
        INTO v_lam USING v_ids;
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
               NULLIF(btrim(e ->> 'taxa_perfm'), '') AS taxa_perfm
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
               bool_or(r.taxa_adm IS NULL AND r.taxa_perfm IS NULL) AS has_empty
        FROM lam_rows r
        WHERE r.dt_comptc = (SELECT max(q.dt_comptc) FROM lam_rows q WHERE q.cnpj = r.cnpj)
        GROUP BY r.cnpj, r.dt_comptc
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
    -- ONE disclosed source per fund, never a mix of two: the lâmina when it
    -- gives a fee, else cad_fi.
    disc AS (
        SELECT g.cnpj, g.fund_name, g.fetched_at, g.dt_ini_exerc,
               (l.cnpj IS NOT NULL AND (l.adm_min IS NOT NULL OR l.perfm IS NOT NULL
                                        OR l.n_perfm > 1)) AS use_lam,
               l.dt_comptc AS lam_dt, l.n_classes, l.n_adm, l.n_perfm, l.has_empty,
               l.adm_lo, l.adm_hi, l.adm_min, l.adm_max, l.perfm AS lam_perfm,
               g.taxa_adm, g.taxa_perfm, g.inf_taxa_adm, g.inf_taxa_perfm
        FROM reg g
        LEFT JOIN lam l ON l.cnpj = g.cnpj
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
               -- The newest month SILO holds for the age; never today's date.
               (SELECT max(z.dt_comptc) FROM public.cvm_fi_balancete_resumo z) AS newest_month
        FROM pair a
    ),
    page (cnpj, fund_name, month, nav, adm_fee_flow, adm_fee_pct_annual_est,
          perf_fee_flow, perf_fee_pct_annual_est, fiscal_reset_suspect,
          disclosed_taxa_adm, disclosed_taxa_adm_min, disclosed_taxa_adm_max,
          disclosed_taxa_perfm, disclosed_taxa_adm_info, disclosed_taxa_perfm_info,
          disclosed_source, disclosed_as_of, disclosed_age_months,
          disclosed_n_classes, disclosed_note, estimate_label) AS (
        SELECT e.cnpj, e.fund_name, e.dt_comptc, e.nav,
               e.adm_flow,
               round(e.adm_flow * 12 / NULLIF(e.nav, 0) * 100, 4),
               e.perf_flow,
               round(e.perf_flow * 12 / NULLIF(e.nav, 0) * 100, 4),
               COALESCE(e.reset_suspect, FALSE),
               -- Lâmina: one fee only when every class discloses the same one.
               CASE WHEN e.use_lam THEN (CASE WHEN e.n_adm = 1 AND NOT e.has_empty THEN e.adm_lo END)
                    ELSE e.taxa_adm END,
               CASE WHEN e.use_lam THEN e.adm_min END,
               CASE WHEN e.use_lam THEN e.adm_max END,
               CASE WHEN e.use_lam THEN (CASE WHEN e.n_perfm = 1 AND NOT e.has_empty THEN e.lam_perfm END)
                    ELSE e.taxa_perfm::text END,
               CASE WHEN e.use_lam THEN NULL ELSE e.inf_taxa_adm END,
               CASE WHEN e.use_lam THEN NULL ELSE e.inf_taxa_perfm END,
               CASE WHEN e.use_lam THEN 'cvm_fi_lamina'
                    WHEN COALESCE(e.taxa_adm, e.taxa_perfm) IS NOT NULL
                         OR COALESCE(e.inf_taxa_adm, e.inf_taxa_perfm) IS NOT NULL
                    THEN 'cvm_fund_registry (cad_fi)' END,
               CASE WHEN e.use_lam THEN e.lam_dt
                    WHEN COALESCE(e.taxa_adm, e.taxa_perfm) IS NOT NULL
                         OR COALESCE(e.inf_taxa_adm, e.inf_taxa_perfm) IS NOT NULL
                    THEN (e.fetched_at AT TIME ZONE 'America/Sao_Paulo')::date END,
               CASE WHEN e.use_lam AND e.newest_month IS NOT NULL THEN
                    ((extract(year FROM e.newest_month) - extract(year FROM e.lam_dt)) * 12
                     + extract(month FROM e.newest_month) - extract(month FROM e.lam_dt))::int END,
               CASE WHEN e.use_lam THEN e.n_classes END,
               CASE
                   WHEN e.use_lam AND (e.n_adm > 1 OR e.n_perfm > 1) THEN
                       'the fund''s ' || e.n_classes || ' classes disclose different fees: the single value is NULL, read the min and max'
                   WHEN e.use_lam AND e.has_empty THEN
                       'at least one class filed no fee: NULL is not a zero fee'
                   WHEN e.use_lam AND e.n_adm = 0 THEN
                       'the lâmina filed no administration fee: NULL is not a zero fee'
                   WHEN NOT e.use_lam AND e.taxa_adm IS NULL
                        AND (e.taxa_perfm IS NOT NULL OR e.inf_taxa_adm IS NOT NULL
                             OR e.inf_taxa_perfm IS NOT NULL) THEN
                       'cad_fi filed no administration fee rate: NULL is not a zero fee'
                   WHEN NOT e.use_lam AND e.taxa_adm IS NULL AND e.taxa_perfm IS NULL
                        AND e.inf_taxa_adm IS NULL AND e.inf_taxa_perfm IS NULL THEN
                       'no disclosed fee in the lâmina or in cad_fi: NULL is not a zero fee'
               END,
               CASE
                   WHEN e.dt_comptc IS NULL THEN
                       'no estimate: no balancete filed'
                       || CASE WHEN v_month IS NULL THEN '' ELSE ' for ' || to_char(v_month, 'YYYY-MM') END
                   WHEN e.reset_confirmed THEN
                       'estimate from the balancete accruals: this month''s accumulated fee alone, because cad_fi DT_INI_EXERC puts the fiscal-year start in this month; x 12 / NAV'
                   WHEN NOT e.has_prev THEN
                       'no estimate: no balancete for the previous month, so the month''s accrual is unknown'
                   WHEN e.reset_suspect THEN
                       'no estimate: the accumulated administration fee fell, the fund''s fiscal-year reset month, and no cad_fi DT_INI_EXERC confirms it'
                   WHEN e.adm_acc IS NULL THEN
                       'estimate from the balancete accruals; no administration fee account filed this month'
                   ELSE
                       'estimate from the balancete accruals: (previous minus current accumulated fee) x 12 / NAV, not the disclosed fee'
               END
        FROM est e
        ORDER BY e.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fund_name, g.month, g.nav, g.adm_fee_flow, g.adm_fee_pct_annual_est,
           g.perf_fee_flow, g.perf_fee_pct_annual_est, g.fiscal_reset_suspect,
           g.disclosed_taxa_adm, g.disclosed_taxa_adm_min, g.disclosed_taxa_adm_max,
           g.disclosed_taxa_perfm, g.disclosed_taxa_adm_info, g.disclosed_taxa_perfm_info,
           g.disclosed_source, g.disclosed_as_of, g.disclosed_age_months,
           g.disclosed_n_classes, g.disclosed_note, g.estimate_label
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
    'Fees per fund, two kinds of number that are never mixed. DISCLOSED (disclosed_*): the fee the fund published, from the lâmina (cvm_fi_lamina, newest reference month) first and cad_fi (cvm_fund_registry taxa_adm / taxa_perfm / inf_taxa_*) as the fallback, ONE source per fund; disclosed_source and disclosed_as_of say which and when (the lâmina also gives disclosed_age_months). A NULL disclosed part is not a zero fee; when the fund''s classes disclose different fees the single value is NULL and the min / max and disclosed_note say so. ESTIMATE (adm_fee_flow, perf_fee_flow and the _pct_annual_est columns): from the balancete accruals (cvm_fi_balancete_resumo): the fee accounts accumulate from each fund''s own fiscal-year start and are filed negative, so the month''s accrual is previous minus current accumulated value (served positive = cost; a negative performance accrual is a reversed provision), annualised x 12 / NAV x 100, NAV = groups 6 + 7 + 8 of the month. In the fiscal-year reset month the accumulated fee falls: fiscal_reset_suspect is TRUE and the estimate is NULL, unless cad_fi DT_INI_EXERC puts the fiscal-year start in that month, in which case the month''s accumulated value alone is the accrual. estimate_label says on every row that the estimate is an estimate and why one is missing; it is never presented as the disclosed fee. p_month = the balancete month (NULL = each fund''s newest). One row per distinct CNPJ; more than 200 CNPJs RAISES 22023.';


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

COMMIT;
