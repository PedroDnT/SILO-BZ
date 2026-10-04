-- Migration 70: the three FIDC tranche percentage columns hold any value CVM files.
--
-- Issue #556. The 2013-2024 backfill (run 37219110740, 2026-10-04) failed five
-- months of tab X_2/X_3/X_6 (2019-08, 2020-01, 2020-07, 2022-04, 2023-12) with
-- "NumericValueOutOfRange: numeric field overflow, precision 20, scale 6": CVM
-- filed a percentage with an absolute value of at least 1e14 in each of them.
-- These fields are dirty as filed. They are stored as filed, never rescaled,
-- clipped or nulled, so the columns become unconstrained NUMERIC:
--   cvm_fidc_tranche.vl_rentab_mes       (TAB_X_VL_RENTAB_MES)
--   cvm_fidc_tranche.pr_desemp_esperado  (TAB_X_PR_DESEMP_ESPERADO)
--   cvm_fidc_tranche.pr_desemp_real      (TAB_X_PR_DESEMP_REAL)
-- Dropping a numeric typmod is binary-coercible: no table rewrite.
--
-- Guarded like 03_precision.sql: it fires only while a column still has a
-- precision, so every later bootstrap is a no-op. The one dependent measured
-- live on 2026-10-04 is the plain view vw_fidc_tranche_detail (07), which
-- Postgres requires to be dropped for the retype. It is recreated in the same
-- block from its own live definition, with its grants, so it never goes
-- missing between this migration and the next analytical apply. If anything
-- else depends on these columns or on that view, the block raises a NOTICE and
-- changes nothing: never CASCADE (see 54 and 58).

DO $mig70$
DECLARE
    v_view    regclass := to_regclass('public.vw_fidc_tranche_detail');
    v_def     text;
    v_grants  text[];
    v_g       text;
    v_others  text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'cvm_fidc_tranche'
          AND column_name IN ('vl_rentab_mes', 'pr_desemp_esperado', 'pr_desemp_real')
          AND numeric_precision IS NOT NULL
    ) THEN
        RETURN;
    END IF;

    -- Every view/matview that depends on the three columns, other than
    -- vw_fidc_tranche_detail, plus anything that depends on that view.
    SELECT string_agg(DISTINCT dep, ', ') INTO v_others
    FROM (
        SELECT dc.oid::regclass::text AS dep
        FROM pg_depend d
        JOIN pg_rewrite r ON r.oid = d.objid
        JOIN pg_class dc ON dc.oid = r.ev_class
        JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
        WHERE d.refobjid = 'public.cvm_fidc_tranche'::regclass
          AND a.attname IN ('vl_rentab_mes', 'pr_desemp_esperado', 'pr_desemp_real')
          AND dc.oid IS DISTINCT FROM v_view
        UNION ALL
        SELECT dc.oid::regclass::text
        FROM pg_depend d
        JOIN pg_rewrite r ON r.oid = d.objid
        JOIN pg_class dc ON dc.oid = r.ev_class
        WHERE v_view IS NOT NULL
          AND d.refobjid = v_view
          AND dc.oid <> v_view
    ) s;

    IF v_others IS NOT NULL THEN
        RAISE NOTICE 'migration 70 skipped: % depend on cvm_fidc_tranche percentage columns or on vw_fidc_tranche_detail; widen by hand after reviewing them', v_others;
        RETURN;
    END IF;

    IF v_view IS NOT NULL THEN
        v_def := pg_get_viewdef(v_view, true);
        SELECT array_agg(format('GRANT %s ON public.vw_fidc_tranche_detail TO %s',
                                g.privilege_type,
                                CASE WHEN g.grantee = 'PUBLIC' THEN 'PUBLIC'
                                     ELSE quote_ident(g.grantee) END))
          INTO v_grants
        FROM information_schema.role_table_grants g
        WHERE g.table_schema = 'public' AND g.table_name = 'vw_fidc_tranche_detail'
          AND g.grantee <> (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = v_view);
        DROP VIEW public.vw_fidc_tranche_detail;
    END IF;

    ALTER TABLE public.cvm_fidc_tranche
        ALTER COLUMN vl_rentab_mes      TYPE NUMERIC,
        ALTER COLUMN pr_desemp_esperado TYPE NUMERIC,
        ALTER COLUMN pr_desemp_real     TYPE NUMERIC;

    IF v_view IS NOT NULL THEN
        EXECUTE 'CREATE VIEW public.vw_fidc_tranche_detail AS ' || v_def;
        IF v_grants IS NOT NULL THEN
            FOREACH v_g IN ARRAY v_grants LOOP
                EXECUTE v_g;
            END LOOP;
        END IF;
    END IF;
END
$mig70$;
