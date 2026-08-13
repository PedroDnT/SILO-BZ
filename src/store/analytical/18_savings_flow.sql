-- =============================================================================
-- 18_savings_flow.sql
-- mv_savings_flow_monthly: fund flows (FI/ETF/FII/FIDC) vs. Selic/CDI, monthly.
--
-- PROVENANCE: this object existed in production but nowhere in this repo —
-- created directly against Supabase, outside version control. Captured via
-- `pg_get_viewdef` (scripts/audit_matview_dependents.py) and brought under
-- version control here so it (a) survives a schema rebuild instead of
-- silently blocking one, and (b) is reviewable/diffable like everything else
-- in this layer. Definition reproduced as found — not redesigned — so this
-- file changes nothing about what the object returns.
--
-- Depends on fact_fund_monthly (04), so it applies AFTER it and is dropped
-- CASCADE by fact_fund_monthly's own re-create; this file's job is to put it
-- back every apply, same as every other object here.
-- =============================================================================

BEGIN;
SET statement_timeout = '5min';

DROP MATERIALIZED VIEW IF EXISTS mv_savings_flow_monthly CASCADE;

CREATE MATERIALIZED VIEW mv_savings_flow_monthly AS
WITH etf_cnpjs AS (
    SELECT DISTINCT cvm_etf_registry.cnpj
    FROM cvm_etf_registry
    WHERE cvm_etf_registry.cnpj IS NOT NULL
), fi AS (
    SELECT date_trunc('month'::text, f.period::timestamp with time zone)::date AS month,
        CASE
            WHEN e.cnpj IS NOT NULL THEN 'etf'::text
            ELSE 'fi'::text
        END AS vehicle,
        sum(f.captc_mes)::numeric(28,2) AS inflow,
        sum(f.resg_mes)::numeric(28,2) AS outflow,
        NULL::numeric(28,2) AS amort,
        sum(f.vl_patrim_liq)::numeric(28,2) AS aum,
        count(DISTINCT f.cnpj) AS n_funds
    FROM fact_fund_monthly f
        LEFT JOIN etf_cnpjs e USING (cnpj)
    WHERE f.entity_type = 'fi'::text
    GROUP BY (date_trunc('month'::text, f.period::timestamp with time zone)::date), (
        CASE
            WHEN e.cnpj IS NOT NULL THEN 'etf'::text
            ELSE 'fi'::text
        END)
), fii AS (
    SELECT date_trunc('month'::text, fact_fund_monthly.period::timestamp with time zone)::date AS month,
        'fii'::text AS vehicle,
        NULL::numeric(28,2) AS inflow,
        NULL::numeric(28,2) AS outflow,
        NULL::numeric(28,2) AS amort,
        sum(fact_fund_monthly.vl_patrim_liq)::numeric(28,2) AS aum,
        count(DISTINCT fact_fund_monthly.cnpj) AS n_funds
    FROM fact_fund_monthly
    WHERE fact_fund_monthly.entity_type = 'fii'::text
    GROUP BY (date_trunc('month'::text, fact_fund_monthly.period::timestamp with time zone)::date)
), fidc_pl AS (
    SELECT DISTINCT ON (cvm_fidc_mensal.cnpj, cvm_fidc_mensal.period) cvm_fidc_mensal.cnpj,
        cvm_fidc_mensal.period,
        cvm_fidc_mensal.vl_patrim_liq
    FROM cvm_fidc_mensal
    ORDER BY cvm_fidc_mensal.cnpj, cvm_fidc_mensal.period, cvm_fidc_mensal.fetched_at DESC
), fidc_aum AS (
    SELECT date_trunc('month'::text, fidc_pl.period::timestamp with time zone)::date AS month,
        sum(fidc_pl.vl_patrim_liq)::numeric(28,2) AS aum,
        count(DISTINCT fidc_pl.cnpj) AS n_funds
    FROM fidc_pl
    GROUP BY (date_trunc('month'::text, fidc_pl.period::timestamp with time zone)::date)
), fidc_fl AS (
    SELECT date_trunc('month'::text, cvm_fidc_tranche_flows.period::timestamp with time zone)::date AS month,
        sum(cvm_fidc_tranche_flows.vl_total) FILTER (WHERE cvm_fidc_tranche_flows.tp_oper = 'Captações no Mês'::text)::numeric(28,2) AS inflow,
        sum(cvm_fidc_tranche_flows.vl_total) FILTER (WHERE cvm_fidc_tranche_flows.tp_oper = ANY (ARRAY['Resgates no Mês'::text, 'Amortizações'::text]))::numeric(28,2) AS outflow,
        sum(cvm_fidc_tranche_flows.vl_total) FILTER (WHERE cvm_fidc_tranche_flows.tp_oper = 'Amortizações'::text)::numeric(28,2) AS amort
    FROM cvm_fidc_tranche_flows
    GROUP BY (date_trunc('month'::text, cvm_fidc_tranche_flows.period::timestamp with time zone)::date)
), fidc AS (
    SELECT COALESCE(a.month, f.month) AS month,
        'fidc'::text AS vehicle,
        f.inflow,
        f.outflow,
        f.amort,
        a.aum,
        a.n_funds
    FROM fidc_aum a
        FULL JOIN fidc_fl f USING (month)
), unioned AS (
    SELECT fi.month, fi.vehicle, fi.inflow, fi.outflow, fi.amort, fi.aum, fi.n_funds
    FROM fi
    UNION ALL
    SELECT fii.month, fii.vehicle, fii.inflow, fii.outflow, fii.amort, fii.aum, fii.n_funds
    FROM fii
    UNION ALL
    SELECT fidc.month, fidc.vehicle, fidc.inflow, fidc.outflow, fidc.amort, fidc.aum, fidc.n_funds
    FROM fidc
), selic AS (
    SELECT DISTINCT ON ((date_trunc('month'::text, bacen_sgs.reference_date::timestamp with time zone)), bacen_sgs.series_code)
        date_trunc('month'::text, bacen_sgs.reference_date::timestamp with time zone)::date AS month,
        bacen_sgs.series_code,
        bacen_sgs.value
    FROM bacen_sgs
    WHERE bacen_sgs.series_code = ANY (ARRAY[432, 12])
    ORDER BY (date_trunc('month'::text, bacen_sgs.reference_date::timestamp with time zone)), bacen_sgs.series_code, bacen_sgs.reference_date DESC
)
SELECT u.month,
    u.vehicle,
    u.inflow,
    u.outflow,
    u.amort,
    (u.inflow - u.outflow)::numeric(28,2) AS net_flow,
    u.aum,
    u.n_funds,
    s432.value AS selic_meta,
    s12.value AS cdi
FROM unioned u
    LEFT JOIN selic s432 ON s432.month = u.month AND s432.series_code = 432
    LEFT JOIN selic s12 ON s12.month = u.month AND s12.series_code = 12
ORDER BY u.month, u.vehicle;

-- api.mv_savings_flow_monthly: a plain passthrough view over the matview
-- above, also found live and also nowhere in this repo. CASCADE-dropping
-- mv_savings_flow_monthly (its only dependent, per the same audit) destroys
-- this too, so it must be recreated in the same pass. CREATE SCHEMA IF NOT
-- EXISTS so this file is self-contained on a fresh database rather than
-- assuming the schema already exists — the "api" schema itself predates this
-- repo's "no public API" architecture decision (see CLAUDE.md) and is not
-- otherwise used here; reproduced as found, not extended.
CREATE SCHEMA IF NOT EXISTS api;

CREATE OR REPLACE VIEW api.mv_savings_flow_monthly AS
SELECT month,
    vehicle,
    inflow,
    outflow,
    amort,
    net_flow,
    aum,
    n_funds,
    selic_meta,
    cdi
FROM mv_savings_flow_monthly;

-- 12_grants_and_rls.sql (the repo's usual home for these) runs BEFORE this
-- file, and CASCADE now actually drops+recreates both objects on every apply
-- (they used to never be reached at all, since the drop was silently failing
-- upstream — see 04_fact_fund_monthly.sql's comment). Without granting here,
-- every apply would recreate them with default privileges and anon/
-- authenticated would silently lose PostgREST access — caught by Cursor
-- Bugbot on PR #83 before it ever reached production.
GRANT USAGE ON SCHEMA api TO anon, authenticated;
GRANT SELECT ON mv_savings_flow_monthly     TO anon, authenticated;
GRANT SELECT ON api.mv_savings_flow_monthly TO anon, authenticated;

COMMIT;
