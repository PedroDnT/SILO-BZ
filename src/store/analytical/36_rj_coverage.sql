-- =============================================================================
-- 36_rj_coverage.sql
-- RJ coverage metric (#846, epic #841): of the cases each source discovered,
-- how many have at least one document link, per tribunal and per source.
--
--   public.rj_coverage  internal view, one row per (tribunal, source).
--
-- The tribunal is read from the CNJ number itself (Res. CNJ 65/2008:
-- NNNNNNN-DD.AAAA.J.TR.OOOO; J = 8 is the state courts, TR the state), so a
-- case from any source lands on the same tribunal. A number from another
-- branch of justice (J <> 8) is reported under its J.TR code, never guessed.
--
-- n_with_documents counts any document of the same process, from any source;
-- n_with_aj_documents counts only links read from an administrador judicial
-- website (source aj_site:*), which is what #847 needs to judge the free route
-- (reject it if coverage stays under about 40 % after all AJ adapters run).
--
-- No client grant: rj_case / rj_document are landing tables.
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regclass('public.rj_document') IS NULL OR to_regclass('public.rj_case') IS NULL THEN
        RAISE EXCEPTION '36_rj_coverage.sql reads rj_case and rj_document; apply migration 75 first';
    END IF;
END
$guard$;

CREATE OR REPLACE VIEW public.rj_coverage AS
WITH tr(code, sigla) AS (
    VALUES ('801','TJAC'),('802','TJAL'),('803','TJAP'),('804','TJAM'),('805','TJBA'),('806','TJCE'),
           ('807','TJDFT'),('808','TJES'),('809','TJGO'),('810','TJMA'),('811','TJMT'),('812','TJMS'),
           ('813','TJMG'),('814','TJPA'),('815','TJPB'),('816','TJPR'),('817','TJPE'),('818','TJPI'),
           ('819','TJRJ'),('820','TJRN'),('821','TJRS'),('822','TJRO'),('823','TJRR'),('824','TJSC'),
           ('825','TJSE'),('826','TJSP'),('827','TJTO')
),
cases AS (
    SELECT c.numero_processo,
           CASE WHEN c.source LIKE 'aj_site:%' THEN 'aj_site' ELSE c.source END AS source,
           substr(c.numero_processo, 14, 3) AS jtr
    FROM public.rj_case c
),
docs AS (
    SELECT d.numero_processo,
           bool_or(true) AS any_doc,
           bool_or(d.source LIKE 'aj_site:%') AS aj_doc
    FROM public.rj_document d
    GROUP BY d.numero_processo
)
SELECT COALESCE(tr.sigla, 'J.TR ' || substr(k.jtr, 1, 1) || '.' || substr(k.jtr, 2, 2)) AS tribunal,
       k.source,
       count(DISTINCT k.numero_processo)                                        AS n_cases,
       count(DISTINCT k.numero_processo) FILTER (WHERE d.any_doc)               AS n_with_documents,
       count(DISTINCT k.numero_processo) FILTER (WHERE d.aj_doc)                AS n_with_aj_documents,
       round(100.0 * count(DISTINCT k.numero_processo) FILTER (WHERE d.aj_doc)
             / NULLIF(count(DISTINCT k.numero_processo), 0), 1)                 AS pct_with_aj_documents
FROM (SELECT DISTINCT numero_processo, source, jtr FROM cases) k
LEFT JOIN tr ON tr.code = k.jtr
LEFT JOIN docs d ON d.numero_processo = k.numero_processo
GROUP BY 1, 2;

REVOKE ALL ON public.rj_coverage FROM PUBLIC;

COMMENT ON VIEW public.rj_coverage IS
    'Internal (no client grant): RJ coverage per (tribunal read from the CNJ number, source family). n_with_aj_documents = cases with at least one link read from an administrador judicial website; #847 judges the free route on pct_with_aj_documents (#846).';

COMMIT;
