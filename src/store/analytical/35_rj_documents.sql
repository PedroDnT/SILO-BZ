-- =============================================================================
-- 35_rj_documents.sql
-- The new-document signal for RJ case documents (#845, epic #841).
--
--   public.rj_document_new  internal view: every rj_document row first seen
--                           today (Brasília calendar day), with its case.
--
-- "New" is first_seen_at, which the collector never writes (it is the
-- column's DEFAULT at the first insert), so the signal needs no extra state.
-- A site read for the first time makes all its documents new on that day.
--
-- No client grant: rj_case / rj_document are landing tables. Serving them
-- through schema api is a later decision (#846).
-- =============================================================================

BEGIN;
SET statement_timeout = '30s';

DO $guard$
BEGIN
    IF to_regclass('public.rj_document') IS NULL OR to_regclass('public.rj_case') IS NULL THEN
        RAISE EXCEPTION '35_rj_documents.sql reads rj_case and rj_document; apply migration 75 first';
    END IF;
END
$guard$;

CREATE OR REPLACE VIEW public.rj_document_new AS
SELECT d.numero_processo,
       c.devedor_nome,
       c.aj_name,
       d.tipo,
       d.titulo,
       d.url,
       d.found_on,
       d.source,
       d.http_status,
       d.first_seen_at
FROM public.rj_document d
LEFT JOIN public.rj_case c
       ON c.numero_processo = d.numero_processo AND c.source = d.source
WHERE (d.first_seen_at AT TIME ZONE 'America/Sao_Paulo')::date
      = (now() AT TIME ZONE 'America/Sao_Paulo')::date;

REVOKE ALL ON public.rj_document_new FROM PUBLIC;

COMMENT ON VIEW public.rj_document_new IS
    'Internal (no client grant): RJ case document links first seen today, Brasília calendar day (first_seen_at is set once, at the first insert). A site read for the first time makes all its documents new that day (#845).';

COMMIT;
