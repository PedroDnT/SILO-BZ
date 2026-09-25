-- =============================================================================
-- 25_api_filing_screens.sql
-- Three FILING-BEHAVIOUR screens, served through schema `api` (catalog v36):
--
--   api.screen_restatements   funds with an unusual count / rate of FNET
--                             re-filings (versao > 1, RE voluntary vs RC
--                             CVM-required) over a trailing delivery window.
--   api.screen_late_filers    FIIs / FIDCs whose monthly informe reached FNET
--                             more than p_min_days_late days after the deadline
--                             Resolução CVM 175 states for it, in at least
--                             p_min_late reference months.
--   api.screen_silent_filers  funds the CVM registry still lists as active that
--                             have not filed their periodic informe for
--                             p_min_silent_months complete months.
--
-- SIGNALS, NOT VERDICTS — the house rule of 23_api_screens.sql, unchanged:
-- every row carries `screen` and `params`; no column is a score; the COMMENT
-- and catalog().screens.<name>.meaning say what else produces the same row.
--
-- WHY A NEW FILE, AND WHY THESE ARE NOT WRAPPERS. The seven screens in 23 wrap
-- the public functions the dashboard reads (15_fraud_screens.sql) so the page
-- and the API cannot disagree. No page runs these three, so there is no second
-- reader to agree with: the api function IS the one definition. 23 keeps its
-- "wrappers only" invariant (tests/test_api_screens_contract.py pins it).
--
-- FUND IDENTITY. FNET rows carry no CNPJ; a document is a fund's only through
-- a cnpjFundo row in fnet_document_filter (the CNPJ SILO queried with). The
-- two FNET screens read ONLY those links — never fund_name, which is served as
-- FNET's label for reading and joined on nothing (CLAUDE.md: no name matching,
-- ever). A document the fortnightly sweep has not linked yet is invisible to
-- them, not attributed. The silent screen reads CVM's own CNPJ-keyed tables.
--
-- "LATE" IS MEASURED AGAINST A CITED RULE, NOTHING ELSE. The deadline is the
-- text of Resolução CVM 175 as consolidated on conteudo.cvm.gov.br (read
-- 2026-09-25):
--   * FIDC — Anexo Normativo II, art. 27, III: the administrator sends the
--     informe mensal to CVM "observando o prazo de 15 (quinze) dias após o
--     encerramento do mês a que se referirem as informações";
--   * FII  — Anexo Normativo III, art. 36, I: "mensalmente, até 15 (quinze)
--     dias após o encerramento do mês a que se referir, o formulário
--     eletrônico cujo conteúdo reflita o Suplemento I".
-- The deadline day is the month's last day + 15 calendar days (the text says
-- "dias", not "dias úteis"). Existing funds had until 2024-11-29 (FIDC) and
-- 2025-06-30 (everyone else, FII included) to adapt to the resolution, so a
-- reference month is evaluated only from the first full month after its
-- family's adaptation deadline — 2024-12 for FIDC, 2025-07 for FII — and an
-- earlier month is not measured at all (its deadline, under the predecessor
-- instructions, is not cited here). SILO applies no holiday calendar: a
-- deadline falling on a weekend or holiday may legitimately roll forward,
-- which is what p_min_days_late (default 5) absorbs. A delivery past the
-- deadline is a timestamp compared with a text — not a finding that a rule
-- was broken (CVM can grant extensions; FNET's delivered_at is the upload).
--
-- "SILENT" READS CVM's DEEP HISTORY, NOT FNET's. FNET history is still being
-- backfilled, so an informe missing from the register proves nothing. The
-- silent screen reads dim_fund (the last period each fund filed in CVM's
-- monthly / daily datasets, per family) against latest_complete_period(family)
-- — the same honest anchor the dormant screens use — and the registry's own
-- is_active flag. FNET appears there only as context (the newest document
-- delivered for the CNPJ, when one is linked).
--
-- PRIVILEGES, ROW CAP: exactly 23's. SECURITY DEFINER with an empty pinned
-- search_path, every relation schema-qualified; REVOKE from PUBLIC, GRANT to
-- anon / authenticated; silo_api gets no grant (no /v1 route serves a screen,
-- the decision 20/21/23 took). One page plus one row, then assert_row_cap
-- REFUSES with 22023 above 1000 — never trimmed. Out-of-range or NULL
-- thresholds raise 22023 naming the range; nothing is clamped.
--
-- Ordering: after 01 (dim_fund), 04 (latest_complete_period), 19
-- (api.assert_row_cap) and migration 42 (the FNET register). The guard below
-- fails the apply loudly if any is missing.
-- =============================================================================

BEGIN;
-- Apply-time guard for this DDL transaction only (the runtime timeout is the
-- calling role's, as in 19).
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL THEN
        RAISE EXCEPTION '25_api_filing_screens.sql needs api.assert_row_cap from 19_api_contract.sql; apply 19 first';
    END IF;
    IF to_regclass('public.fnet_document') IS NULL
       OR to_regclass('public.fnet_document_filter') IS NULL THEN
        RAISE EXCEPTION '25_api_filing_screens.sql reads the FNET register; apply migration 42_fnet_document.sql first';
    END IF;
    IF to_regclass('public.dim_fund') IS NULL
       OR to_regprocedure('public.latest_complete_period(text)') IS NULL THEN
        RAISE EXCEPTION '25_api_filing_screens.sql reads dim_fund and latest_complete_period(); apply 01 and 04 first';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- Restatements (FII / FIDC / ETF, FNET) — funds whose re-filings in a
-- trailing delivery window cross both a count and a rate threshold.
-- ---------------------------------------------------------------------------
-- Grain: one row per cnpjFundo link. `documents` is every document FNET
-- returned for that CNPJ with a delivery day in the window; `restatements`
-- the ones with versao > 1 (narrowed to one modalidade by p_modalidade);
-- restatements_re / restatements_rc split them as FNET publishes modalidade,
-- whatever p_modalidade says. restatement_pct = restatements / documents × 100.
-- p_modalidade = 'RC', p_min_restatements = 1, p_min_rate_pct = 0 lists every
-- fund with a restatement CVM required in the window.
CREATE OR REPLACE FUNCTION api.screen_restatements(
    p_months           INT     DEFAULT 12,   -- trailing delivery window, months, 1..36
    p_end              DATE    DEFAULT NULL, -- last delivery day of the window; NULL = today
    p_min_restatements INT     DEFAULT 3,    -- re-filings (versao > 1) in the window, 1..1000
    p_min_rate_pct     NUMERIC DEFAULT 20,   -- re-filings as percent of the fund's documents in the window, 0..100
    p_modalidade       TEXT    DEFAULT NULL  -- RE | RC: count only that kind; NULL = every versao > 1
)
RETURNS TABLE (
    cnpj             TEXT,
    tipo_fundo       TEXT,
    fund_name        TEXT,
    window_from      DATE,
    window_to        DATE,
    documents        BIGINT,
    restatements     BIGINT,
    restatements_re  BIGINT,
    restatements_rc  BIGINT,
    restatement_pct  NUMERIC,
    last_restated_at TIMESTAMP,
    screen           TEXT,
    params           JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_to   DATE;
    v_from DATE;
BEGIN
    IF p_months IS NULL OR p_months < 1 OR p_months > 36 THEN
        RAISE EXCEPTION 'screen_restatements: p_months must be between 1 and 36, got %', p_months
            USING ERRCODE = '22023';
    END IF;
    IF p_min_restatements IS NULL OR p_min_restatements < 1 OR p_min_restatements > 1000 THEN
        RAISE EXCEPTION 'screen_restatements: p_min_restatements must be between 1 and 1000, got %', p_min_restatements
            USING ERRCODE = '22023';
    END IF;
    IF p_min_rate_pct IS NULL OR p_min_rate_pct < 0 OR p_min_rate_pct > 100 THEN
        RAISE EXCEPTION 'screen_restatements: p_min_rate_pct must be between 0 and 100 (percent of the fund''s documents), got %', p_min_rate_pct
            USING ERRCODE = '22023';
    END IF;
    IF p_modalidade IS NOT NULL AND p_modalidade NOT IN ('RE', 'RC') THEN
        RAISE EXCEPTION 'screen_restatements: p_modalidade must be RE (voluntary) or RC (required by CVM), or null for both, got %', p_modalidade
            USING ERRCODE = '22023';
    END IF;

    v_to   := COALESCE(p_end, CURRENT_DATE);
    v_from := ((v_to - make_interval(months => p_months))::date + 1);

    RETURN QUERY
    WITH docs AS (
        -- The link row IS the fund (one per (fnet_id, 'cnpjFundo', cnpj) by
        -- uq_fnet_document_filter), so this cannot fan out.
        SELECT l.filter_value AS cnpj, d.fnet_id, d.versao, d.modalidade,
               d.delivered_at, d.fund_name
        FROM public.fnet_document_filter l
        JOIN public.fnet_document d ON d.fnet_id = l.fnet_id
        WHERE l.filter_name = 'cnpjFundo'
          AND d.delivered_at >= v_from::timestamp
          AND d.delivered_at <  (v_to + 1)::timestamp
    ),
    per_fund AS (
        SELECT dc.cnpj,
               count(*) AS n_docs,
               count(*) FILTER (WHERE dc.versao > 1
                                  AND (p_modalidade IS NULL OR dc.modalidade = p_modalidade)) AS n_restated,
               count(*) FILTER (WHERE dc.versao > 1 AND dc.modalidade = 'RE') AS n_re,
               count(*) FILTER (WHERE dc.versao > 1 AND dc.modalidade = 'RC') AS n_rc,
               max(dc.delivered_at) FILTER (WHERE dc.versao > 1
                                  AND (p_modalidade IS NULL OR dc.modalidade = p_modalidade)) AS last_at,
               -- FNET's label on the fund's newest document: for reading only.
               (array_agg(dc.fund_name ORDER BY dc.delivered_at DESC, dc.fnet_id DESC))[1] AS label
        FROM docs dc
        GROUP BY dc.cnpj
    ),
    flagged AS (
        SELECT f.*
        FROM per_fund f
        WHERE f.n_restated >= p_min_restatements
          AND 100.0 * f.n_restated / f.n_docs >= p_min_rate_pct
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT fl.cnpj, tf.tipo_fundo, fl.label, fl.n_docs, fl.n_restated,
               fl.n_re, fl.n_rc,
               round(100.0 * fl.n_restated / fl.n_docs, 1) AS pct,
               fl.last_at
        FROM flagged fl
        -- tipoFundo links of the fund's documents in the window ('1' FII,
        -- '2' FIDC, '3' ETF); NULL when none of them came from a per-type crawl.
        LEFT JOIN LATERAL (
            SELECT string_agg(DISTINCT
                       CASE t.filter_value WHEN '1' THEN 'FII' WHEN '2' THEN 'FIDC' WHEN '3' THEN 'ETF' END,
                       ',') AS tipo_fundo
            FROM docs d2
            JOIN public.fnet_document_filter t
              ON t.fnet_id = d2.fnet_id
             AND t.filter_name = 'tipoFundo'
             AND t.filter_value IN ('1', '2', '3')
            WHERE d2.cnpj = fl.cnpj
        ) tf ON TRUE
        ORDER BY fl.n_restated DESC, fl.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.tipo_fundo, g.label, v_from, v_to,
           g.n_docs, g.n_restated, g.n_re, g.n_rc, g.pct, g.last_at,
           'restatements'::text,
           jsonb_build_object('p_months', p_months,
                              'p_end', p_end,
                              'p_min_restatements', p_min_restatements,
                              'p_min_rate_pct', p_min_rate_pct,
                              'p_modalidade', p_modalidade)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_restatements')
    ORDER BY g.n_restated DESC, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_restatements(INT, DATE, INT, NUMERIC, TEXT) IS
    'SIGNAL, NOT A VERDICT. Funds whose B3 Fundos.NET (FNET) re-filings — documents with versao > 1 — in the trailing p_months of delivery days (ending p_end, default today) number at least p_min_restatements AND make up at least p_min_rate_pct of the fund''s documents in the window. restatements_re (voluntary, Reapresentação Espontânea) and restatements_rc (required by CVM, Reapresentação por Exigência) split them as FNET publishes modalidade; p_modalidade counts only one kind. A fund is known ONLY by its cnpjFundo link (the CNPJ SILO queried FNET with) — never by fund_name, which is FNET''s label, served for reading. The same pattern comes from routine corrections of typos, an administrator or custodian migration that re-submits a whole book, the resolution-175 adaptation, a FNET template change forcing re-submission, one error cascading through consecutive informes, or a CVM supervision sweep that required re-filings across an administrator''s funds; an RC says CVM asked, not what was wrong. Documents not yet linked by the fortnightly sweep and history before SILO''s first crawl are not counted (coverage() fnet_documents). Defaults 12 months, 3 re-filings, 20%. Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): raise the thresholds or pin p_modalidade.';

REVOKE ALL ON FUNCTION api.screen_restatements(INT, DATE, INT, NUMERIC, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_restatements(INT, DATE, INT, NUMERIC, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Late filers (FII / FIDC, FNET) — the monthly informe's first delivery
-- measured against the 15-day deadline Resolução CVM 175 states for it.
-- ---------------------------------------------------------------------------
-- Per (fund, reference month): the FIRST delivery of any versao = 1 document
-- typed 'Informe Mensal Estruturado' and referring to that month. A
-- restatement never makes a month late (it is a later version of a filing
-- already made), and a month with no informe in the register is not counted
-- — the register is partial, and absence is screen_silent_filers' question,
-- answered from CVM's deep tables. The family decides the citation: FNET's
-- tipoFundo link on the informe ('1' FII, '2' FIDC), else the registry when
-- it lists the CNPJ as exactly one of fii / fidc; a CNPJ that stays ambiguous
-- is not evaluated.
--   lag_days          = first delivery day − last day of the reference month
--   days_past_deadline = first delivery day − (last day of the month + 15)
-- A month counts as late when days_past_deadline >= p_min_days_late.
CREATE OR REPLACE FUNCTION api.screen_late_filers(
    p_months        INT  DEFAULT 12,     -- reference months evaluated, ending at p_end, 1..36
    p_end           DATE DEFAULT NULL,   -- any day in the last reference month; NULL = the newest month whose deadline has passed
    p_min_days_late INT  DEFAULT 5,      -- days past the deadline that count as late, 1..90
    p_min_late      INT  DEFAULT 2,      -- late informes a fund needs in the window, 1..36
    p_family        TEXT DEFAULT NULL    -- fii | fidc; NULL = both (output filter)
)
RETURNS TABLE (
    cnpj                TEXT,
    fund_family         TEXT,
    fund_name           TEXT,
    window_from         DATE,
    window_to           DATE,
    informes            BIGINT,
    informes_late       BIGINT,
    max_days_late       INT,
    median_lag_days     NUMERIC,
    last_late_reference DATE,
    deadline_rule       TEXT,
    screen              TEXT,
    params              JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
DECLARE
    v_to   DATE;
    v_from DATE;
BEGIN
    IF p_months IS NULL OR p_months < 1 OR p_months > 36 THEN
        RAISE EXCEPTION 'screen_late_filers: p_months must be between 1 and 36, got %', p_months
            USING ERRCODE = '22023';
    END IF;
    IF p_min_days_late IS NULL OR p_min_days_late < 1 OR p_min_days_late > 90 THEN
        RAISE EXCEPTION 'screen_late_filers: p_min_days_late must be between 1 and 90 days past the deadline, got %', p_min_days_late
            USING ERRCODE = '22023';
    END IF;
    IF p_min_late IS NULL OR p_min_late < 1 OR p_min_late > p_months THEN
        RAISE EXCEPTION 'screen_late_filers: p_min_late must be between 1 and p_months (%), got %', p_months, p_min_late
            USING ERRCODE = '22023';
    END IF;
    IF p_family IS NOT NULL AND p_family NOT IN ('fii', 'fidc') THEN
        RAISE EXCEPTION 'screen_late_filers: p_family must be fii or fidc (the families whose informe mensal deadline is cited), got %', p_family
            USING ERRCODE = '22023';
    END IF;

    -- The newest month m whose deadline (last day + 15) is already behind us:
    -- m + 1 month <= today - 15.
    v_to   := date_trunc('month', COALESCE(p_end, ((CURRENT_DATE - 15) - interval '1 month')::date))::date;
    v_from := (v_to - make_interval(months => p_months - 1))::date;
    IF v_to < DATE '2024-12-01' THEN
        RAISE EXCEPTION 'screen_late_filers: the window ends at % — no reference month before 2024-12 (FIDC) / 2025-07 (FII) is measured, because the deadline cited here is Resolução CVM 175''s and existing funds had until 2024-11-29 (FIDC) and 2025-06-30 (FII) to adapt to it. Move p_end forward.', v_to
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH reg AS (
        -- The registry's word on the family, only where it is unambiguous.
        SELECT r.cnpj, min(r.entity_type) AS fam
        FROM public.cvm_fund_registry r
        WHERE r.entity_type IN ('fii', 'fidc')
        GROUP BY r.cnpj
        HAVING count(DISTINCT r.entity_type) = 1
    ),
    informes AS (
        SELECT l.filter_value AS cnpj,
               date_trunc('month', d.reference_date)::date AS ref_month,
               d.fnet_id, d.delivered_at, d.fund_name,
               (SELECT CASE
                           WHEN bool_or(t.filter_value = '1') AND NOT bool_or(t.filter_value = '2') THEN 'fii'
                           WHEN bool_or(t.filter_value = '2') AND NOT bool_or(t.filter_value = '1') THEN 'fidc'
                       END
                FROM public.fnet_document_filter t
                WHERE t.fnet_id = d.fnet_id AND t.filter_name = 'tipoFundo') AS link_fam
        FROM public.fnet_document_filter l
        JOIN public.fnet_document d ON d.fnet_id = l.fnet_id
        WHERE l.filter_name = 'cnpjFundo'
          AND d.versao = 1
          AND btrim(d.tipo_documento) = 'Informe Mensal Estruturado'
          AND d.reference_date IS NOT NULL
          AND d.reference_date >= v_from
          AND d.reference_date <  (v_to + interval '1 month')::date
    ),
    months AS (
        SELECT i.cnpj, i.ref_month,
               min(i.delivered_at) AS first_delivery,
               CASE WHEN count(DISTINCT i.link_fam) = 1 THEN min(i.link_fam) END AS link_fam,
               (array_agg(i.fund_name ORDER BY i.delivered_at DESC, i.fnet_id DESC))[1] AS label
        FROM informes i
        GROUP BY i.cnpj, i.ref_month
    ),
    measured AS (
        SELECT m.cnpj, x.fam, m.ref_month, m.label, m.first_delivery,
               (m.first_delivery::date - ((m.ref_month + interval '1 month')::date - 1)) AS lag_days,
               (m.first_delivery::date - ((m.ref_month + interval '1 month')::date - 1 + 15)) AS days_past
        FROM months m
        LEFT JOIN reg rg ON rg.cnpj = m.cnpj
        CROSS JOIN LATERAL (SELECT COALESCE(m.link_fam, rg.fam) AS fam) x
        WHERE x.fam IS NOT NULL
          -- The first full month after the family's adaptation deadline.
          AND m.ref_month >= CASE x.fam WHEN 'fidc' THEN DATE '2024-12-01' ELSE DATE '2025-07-01' END
          AND (p_family IS NULL OR x.fam = p_family)
    ),
    per_fund AS (
        SELECT ms.cnpj, ms.fam,
               count(*) AS n_informes,
               count(*) FILTER (WHERE ms.days_past >= p_min_days_late) AS n_late,
               max(ms.days_past) FILTER (WHERE ms.days_past >= p_min_days_late) AS worst,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY ms.lag_days) AS median_lag,
               max(ms.ref_month) FILTER (WHERE ms.days_past >= p_min_days_late) AS last_late,
               (array_agg(ms.label ORDER BY ms.first_delivery DESC))[1] AS label
        FROM measured ms
        GROUP BY ms.cnpj, ms.fam
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT pf.*
        FROM per_fund pf
        WHERE pf.n_late >= p_min_late
        ORDER BY pf.n_late DESC, pf.worst DESC, pf.cnpj
        LIMIT 1001
    )
    SELECT g.cnpj, g.fam, g.label, v_from, v_to,
           g.n_informes, g.n_late, g.worst,
           round(g.median_lag::numeric, 1), g.last_late,
           CASE g.fam
               WHEN 'fidc' THEN 'Resolução CVM 175, Anexo Normativo II, art. 27, III: informe mensal within 15 days after the end of the month it refers to (evaluated from reference month 2024-12, after the FIDC adaptation deadline of 2024-11-29)'
               WHEN 'fii'  THEN 'Resolução CVM 175, Anexo Normativo III, art. 36, I: monthly form (Suplemento I) within 15 days after the end of the month it refers to (evaluated from reference month 2025-07, after the adaptation deadline of 2025-06-30)'
           END,
           'late_filers'::text,
           jsonb_build_object('p_months', p_months,
                              'p_end', p_end,
                              'p_min_days_late', p_min_days_late,
                              'p_min_late', p_min_late,
                              'p_family', p_family)
    FROM page g
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_late_filers')
    ORDER BY g.n_late DESC, g.worst DESC, g.cnpj
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_late_filers(INT, DATE, INT, INT, TEXT) IS
    'SIGNAL, NOT A VERDICT. FIIs and FIDCs whose monthly informe (FNET ''Informe Mensal Estruturado'', first delivery of a versao 1 document) reached B3 Fundos.NET at least p_min_days_late days after the deadline Resolução CVM 175 states for it, in at least p_min_late of the p_months reference months ending at p_end. The deadline is cited, not assumed: FIDC — Anexo Normativo II, art. 27, III; FII — Anexo Normativo III, art. 36, I; both 15 days after the end of the reference month, counted here as calendar days (the text says dias, not dias úteis). A month is measured only from the first full month after the family''s adaptation deadline (2024-12 FIDC, 2025-07 FII); a window ending earlier raises 22023. SILO applies no holiday calendar, so a deadline on a weekend or holiday may legitimately roll forward — p_min_days_late (default 5) absorbs that. informes counts the months measured, informes_late those past the threshold, max_days_late the worst, median_lag_days the fund''s median delivery lag after month end, deadline_rule the citation. A late delivery is a timestamp compared with a rule, not a finding: the same row comes from an extension CVM granted, an upload that FNET timestamped after a delivery made by other means, or an administrator transfer that delayed one month for a whole book; a fund with several classes is measured on its earliest filing. A month with no informe in the register is NOT counted (FNET history is partial; absence is screen_silent_filers). Fund identity is the cnpjFundo link only, never fund_name. Defaults 12 months, 5 days, 2 late months. Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): raise p_min_late or p_min_days_late, or pin p_family.';

REVOKE ALL ON FUNCTION api.screen_late_filers(INT, DATE, INT, INT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_late_filers(INT, DATE, INT, INT, TEXT) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Silent filers (FI / FIDC / FII / FIAGRO, CVM) — registered as active, no
-- periodic informe for p_min_silent_months complete months.
-- ---------------------------------------------------------------------------
-- dim_fund carries, per (cnpj, family), the last period the fund filed in
-- CVM's own dataset: the informe diário for FI (a day), the monthly informe
-- for FIDC / FII / FIAGRO. months_silent counts the complete months after
-- that period's month up to latest_complete_period(family) — the family's
-- newest month CVM has published in full, never today — so a fund is not
-- called silent for a month nobody has been published for yet. The registry
-- row for the same (cnpj, family) must be is_active = TRUE (derived at ingest
-- from CVM's status; registry_status serves the status as filed). FIP files
-- annually and is not screened. p_family narrows the output only.
CREATE OR REPLACE FUNCTION api.screen_silent_filers(
    p_min_silent_months INT  DEFAULT 3,    -- complete months with no filing, 1..120
    p_max_silent_months INT  DEFAULT 24,   -- ...and at most this many, p_min_silent_months..240
    p_family            TEXT DEFAULT NULL  -- fi | fidc | fii | fiagro; NULL = all four (output filter)
)
RETURNS TABLE (
    cnpj                   TEXT,
    fund_family            TEXT,
    fund_name              TEXT,
    registry_status        TEXT,
    last_filed_period      DATE,
    complete_through       DATE,
    months_silent          INT,
    reports_filed          BIGINT,
    registry_nav           NUMERIC,
    registry_nav_date      DATE,
    fnet_last_delivered_at TIMESTAMP,
    screen                 TEXT,
    params                 JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $fn$
#variable_conflict use_column
BEGIN
    IF p_min_silent_months IS NULL OR p_min_silent_months < 1 OR p_min_silent_months > 120 THEN
        RAISE EXCEPTION 'screen_silent_filers: p_min_silent_months must be between 1 and 120, got %', p_min_silent_months
            USING ERRCODE = '22023';
    END IF;
    IF p_max_silent_months IS NULL OR p_max_silent_months < p_min_silent_months OR p_max_silent_months > 240 THEN
        RAISE EXCEPTION 'screen_silent_filers: p_max_silent_months must be between p_min_silent_months (%) and 240, got %', p_min_silent_months, p_max_silent_months
            USING ERRCODE = '22023';
    END IF;
    IF p_family IS NOT NULL AND p_family NOT IN ('fi', 'fidc', 'fii', 'fiagro') THEN
        RAISE EXCEPTION 'screen_silent_filers: p_family must be fi, fidc, fii or fiagro (FIP files annually and is not screened), got %', p_family
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH fam AS (
        SELECT f.fam, public.latest_complete_period(f.fam) AS ct
        FROM (VALUES ('fi'), ('fidc'), ('fii'), ('fiagro')) AS f(fam)
        WHERE p_family IS NULL OR f.fam = p_family
    ),
    silent AS (
        SELECT d.cnpj, d.entity_type, d.last_period, d.n_reports, fa.ct,
               ((extract(year FROM fa.ct) * 12 + extract(month FROM fa.ct))
              - (extract(year FROM d.last_period) * 12 + extract(month FROM d.last_period)))::int AS n_silent
        FROM public.dim_fund d
        JOIN fam fa ON fa.fam = d.entity_type
        WHERE d.last_period IS NOT NULL
    ),
    -- One page + one, then assert_row_cap REFUSES (22023). No cursor.
    page AS (
        SELECT s.cnpj, s.entity_type, r.fund_name, r.status, s.last_period, s.ct,
               s.n_silent, s.n_reports, r.vl_patrim_liq, r.dt_patrim_liq
        FROM silent s
        JOIN public.cvm_fund_registry r
          ON r.cnpj = s.cnpj
         AND r.entity_type = s.entity_type
         AND r.is_active IS TRUE
        WHERE s.n_silent BETWEEN p_min_silent_months AND p_max_silent_months
        ORDER BY s.n_silent, r.vl_patrim_liq DESC NULLS LAST, s.cnpj, s.entity_type
        LIMIT 1001
    )
    SELECT g.cnpj, g.entity_type, g.fund_name, g.status, g.last_period, g.ct,
           g.n_silent, g.n_reports, g.vl_patrim_liq, g.dt_patrim_liq,
           fn.last_at,
           'silent_filers'::text,
           jsonb_build_object('p_min_silent_months', p_min_silent_months,
                              'p_max_silent_months', p_max_silent_months,
                              'p_family', p_family)
    FROM page g
    -- Context, not a criterion: the newest FNET document linked to the CNPJ
    -- (FII / FIDC only are swept). NULL = none linked.
    LEFT JOIN LATERAL (
        SELECT max(d.delivered_at) AS last_at
        FROM public.fnet_document_filter l
        JOIN public.fnet_document d ON d.fnet_id = l.fnet_id
        WHERE l.filter_name = 'cnpjFundo' AND l.filter_value = g.cnpj
    ) fn ON TRUE
    WHERE api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'screen_silent_filers')
    ORDER BY g.n_silent, g.vl_patrim_liq DESC NULLS LAST, g.cnpj, g.entity_type
    LIMIT 1000;
END;
$fn$;

COMMENT ON FUNCTION api.screen_silent_filers(INT, INT, TEXT) IS
    'SIGNAL, NOT A VERDICT. Funds that CVM''s registry (cvm_fund_registry) still lists as active (is_active, derived from the filed status; registry_status is served as filed) whose last periodic informe in CVM''s own dataset — the informe diário for FI, the monthly informe for FIDC, FII and FIAGRO (dim_fund) — is between p_min_silent_months and p_max_silent_months COMPLETE months behind the family''s latest complete period (latest_complete_period, never today), so an unpublished month never reads as silence. reports_filed is the fund''s filed periods; registry_nav / registry_nav_date are the NAV the registry itself carries, with its own date; fnet_last_delivered_at is the newest B3 Fundos.NET document linked to the CNPJ (FII / FIDC only; NULL = none linked) — a fund silent at CVM but still delivering to FNET is the "still filing elsewhere" case. The same row comes from a fund merged, incorporated or liquidated whose registry status CVM has not updated yet; a resolution-175 adaptation that moved reporting to a class CNPJ other than the fund''s; CVM''s dataset lagging the filing itself; or a SILO ingest gap (check coverage() landed_at before reading a family-wide silence). FIP files annually and is not screened. Defaults 3..24 months, every family. Every row carries screen and params. More than 1000 rows RAISES 22023 (never trimmed): pin p_family or narrow p_min_silent_months / p_max_silent_months.';

REVOKE ALL ON FUNCTION api.screen_silent_filers(INT, INT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION api.screen_silent_filers(INT, INT, TEXT) TO anon, authenticated;

COMMIT;
