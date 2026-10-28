-- =============================================================================
-- 37_credit_implied_check.sql
-- The internal check of the calculated debenture rates (#1007, ADR 0004).
--
--   public.credit_implied_vs_anbima  one row per b3_credit_implied_rate row,
--                                    beside ANBIMA's indicative rate of the
--                                    same code on the same day, with the gap
--                                    and two tags.
--
-- PRIVATE. ANBIMA's indicative rate is collected under a permission that
-- covers collection, not redistribution, so this view carries no client grant
-- and no api.* function reads it. It is for the owner and for the daily
-- health reading of the method.
--
-- THE TAGS ARE MEASURED, NOT ASSUMED. On the first run (method v1, trade dates
-- 2026-10-01 to 10-26, 4,816 pairs with an ANBIMA rate on the same day): the
-- median absolute gap was 0.13 pp; 4,359 pairs sat within 1 pp, 388 between
-- 1 and 5 pp, and 69 beyond 5 pp. Those 69 had a median traded volume of
-- BRL 33 thousand against BRL 416 thousand for the pairs within 1 pp.
--   confidence  'checked'    same-day ANBIMA rate exists and |gap| <= 1 pp
--               'divergent'  same-day ANBIMA rate exists and |gap| > 1 pp
--               'unchecked'  no comparable ANBIMA rate: none that day (ANBIMA
--                            keeps 5 sessions per capture) or rate_basis is
--                            pct_di, whose ANBIMA unit is not proven the same
--   outlier     |gap| > 5 pp
--   thin_trade  traded volume under BRL 20 thousand (10% of the rows)
-- gap_pp is implied minus indicative, both in percent a year.
-- =============================================================================

BEGIN;

DO $guard$
BEGIN
    IF to_regclass('public.b3_credit_implied_rate') IS NULL
       OR to_regclass('public.anbima_debenture_indicative') IS NULL THEN
        RAISE EXCEPTION '37_credit_implied_check.sql reads b3_credit_implied_rate and anbima_debenture_indicative; apply the schema and migrations first';
    END IF;
END
$guard$;

CREATE OR REPLACE VIEW public.credit_implied_vs_anbima AS
WITH paired AS (
    SELECT r.codigo, r.trade_date, r.settlement_date, r.trade_classification,
           r.method_version, r.rate_basis, r.volume_brl, r.trade_count,
           r.implied_rate_pct,
           CASE WHEN r.rate_basis <> 'pct_di' THEN a.taxa_indicativa_pct END AS anbima_rate_pct
    FROM public.b3_credit_implied_rate r
    LEFT JOIN public.anbima_debenture_indicative a
           ON a.codigo = r.codigo AND a.data_referencia = r.trade_date
)
SELECT p.codigo, p.trade_date, p.settlement_date, p.trade_classification,
       p.method_version, p.rate_basis, p.volume_brl, p.trade_count,
       p.implied_rate_pct, p.anbima_rate_pct,
       p.implied_rate_pct - p.anbima_rate_pct AS gap_pp,
       CASE WHEN p.anbima_rate_pct IS NULL THEN 'unchecked'
            WHEN abs(p.implied_rate_pct - p.anbima_rate_pct) <= 1 THEN 'checked'
            ELSE 'divergent' END AS confidence,
       COALESCE(abs(p.implied_rate_pct - p.anbima_rate_pct) > 5, FALSE) AS outlier,
       COALESCE(p.volume_brl < 20000, FALSE) AS thin_trade
FROM paired p;

COMMENT ON VIEW public.credit_implied_vs_anbima IS
    'Internal check of b3_credit_implied_rate against anbima_debenture_indicative (same code, same day). gap_pp = implied - indicative, percent a year. confidence: checked (|gap| <= 1 pp), divergent (> 1 pp), unchecked (no comparable ANBIMA rate that day, or pct_di). outlier: |gap| > 5 pp. thin_trade: volume under BRL 20 thousand. Thresholds measured on the first run, 2026-10-01 to 10-26. PRIVATE: ANBIMA data is collected, not redistributable; no grant, never read by schema api.';

REVOKE ALL ON public.credit_implied_vs_anbima FROM PUBLIC;
DO $grants$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'silo_api'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON public.credit_implied_vs_anbima FROM %I', role_name);
        END IF;
    END LOOP;
END
$grants$;

COMMIT;
