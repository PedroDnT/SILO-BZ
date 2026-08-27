-- =============================================================================
-- 04_fact_fund_monthly.sql
-- Materialized view: fact_fund_monthly
-- One row per (cnpj, period, entity_type) across all five fund types.
--
-- Unified column set:
--   period         DATE    — first day of month
--   entity_type    TEXT    — fi | fidc | fiagro | fii | fip
--   vl_patrim_liq  NUMERIC — net asset value (end of month for FI, monthly snap for others)
--   vl_quota       NUMERIC — unit quota value (FI only)
--   nr_cotst       INT     — number of unit-holders
--   vl_inadimpl    NUMERIC — delinquent portfolio value (FIDC / FIAGRO only)
--   pct_yield_mes  NUMERIC — monthly yield % (FII complemento only)
--   captc_mes      NUMERIC — gross inflows over the month (FI only)
--   resg_mes       NUMERIC — gross redemptions over the month (FI only)
--   vl_ativo       NUMERIC — total assets (FII complemento only)
--   quota_subclass_id TEXT — stable FI subclass supplying vl_quota (FI only)
--
-- FI source is daily (cvm_fi_diario) — must be aggregated to monthly. A fund
-- can now have several subclasses under one CNPJ. PL / cotistas are additive,
-- but quota values are not. quota_subclass_id records the one stable subclass
-- whose quota is followed through time; choosing the largest subclass anew in
-- every month can switch units and manufacture million-percent "returns".
-- FIP source is yearly (cvm_fip_periodic) — period mapped to Dec-31 of the year.
-- FII: only doc_subtype = 'complemento' carries yield / cotistas / vl_ativo.
--
-- CASCADE on the drop: every known dependent (dim_administrator, dim_gestor,
-- vw_fii_vs_fiagro, vw_fund_security_yield, mv_savings_flow_monthly +
-- api.mv_savings_flow_monthly) is recreated later in the same apply_analytical.sh
-- pass (13_dim_classification.sql, 07_vw_cross_domain.sql, 18_savings_flow.sql)
-- — captured via scripts/audit_matview_dependents.py before adding CASCADE, not
-- assumed. A plain DROP (no CASCADE) fails as soon as ANY of these exist, which
-- is always true after the first successful apply; that was silently failing
-- on every subsequent run (continue-on-error on the workflow step masked it),
-- so this matview's definition was not actually being refreshed in production.
-- If a NEW ad-hoc dependent shows up outside this repo, CASCADE will drop it
-- too — re-run the audit script before assuming this list is still complete.
-- =============================================================================

BEGIN;
SET statement_timeout = '15min';

DROP MATERIALIZED VIEW IF EXISTS fact_fund_monthly CASCADE;

CREATE MATERIALIZED VIEW fact_fund_monthly AS

WITH fi_per_subclass AS MATERIALIZED (
  SELECT DISTINCT ON (cnpj, id_subclasse, date_trunc('month', dt_comptc))
    cnpj,
    id_subclasse,
    date_trunc('month', dt_comptc)::date AS period,
    dt_comptc,
    vl_patrim_liq,
    vl_quota,
    nr_cotst
  FROM cvm_fi_diario d
  WHERE vl_patrim_liq IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
  ORDER BY
    cnpj,
    id_subclasse,
    date_trunc('month', dt_comptc),
    dt_comptc DESC
),
fi_quota_subclass AS (
  -- Follow one comparable unit through the full history: the largest positive-
  -- quota subclass in the fund's latest available month. A newly introduced
  -- subclass therefore has no invented pre-history; earlier months stay NULL.
  SELECT DISTINCT ON (cnpj)
    cnpj,
    id_subclasse
  FROM fi_per_subclass
  WHERE vl_quota > 0
  ORDER BY
    cnpj,
    period DESC,
    vl_patrim_liq DESC NULLS LAST,
    id_subclasse
),
fi_monthly AS (
  SELECT
    p.cnpj,
    p.period,
    SUM(p.vl_patrim_liq)                                               AS vl_patrim_liq,
    MAX(p.vl_quota) FILTER (WHERE p.id_subclasse = q.id_subclasse)      AS vl_quota,
    SUM(p.nr_cotst)                                                     AS nr_cotst,
    MAX(q.id_subclasse)                                                 AS quota_subclass_id
  FROM fi_per_subclass p
  LEFT JOIN fi_quota_subclass q USING (cnpj)
  GROUP BY p.cnpj, p.period
),
fi_flows AS (
  SELECT
    cnpj,
    date_trunc('month', dt_comptc)::date AS period,
    SUM(captc_dia)                       AS captc_mes,
    SUM(resg_dia)                        AS resg_mes
  FROM cvm_fi_diario d
  WHERE NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
  GROUP BY cnpj, date_trunc('month', dt_comptc)::date
)

  -- -------------------------------------------------------------------------
  -- FI: daily → monthly aggregation
  -- Last-day-of-month PL / cotistas summed to a per-fund total. Quota follows
  -- the stable subclass selected above. Flows are summed across subclasses.
  -- -------------------------------------------------------------------------
  SELECT
    last_day.cnpj,
    last_day.period,
    'fi'                                             AS entity_type,
    last_day.vl_patrim_liq,
    last_day.vl_quota,
    last_day.nr_cotst,
    NULL::numeric                                    AS vl_inadimpl,
    NULL::numeric                                    AS pct_yield_mes,
    flows.captc_mes,
    flows.resg_mes,
    NULL::numeric                                    AS vl_ativo,
    last_day.quota_subclass_id
  FROM fi_monthly last_day
  JOIN fi_flows flows
    ON  flows.cnpj   = last_day.cnpj
    AND flows.period = last_day.period

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIDC: monthly snapshot — direct passthrough
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fidc'          AS entity_type,
    vl_patrim_liq,
    NULL::numeric   AS vl_quota,
    NULL::int       AS nr_cotst,
    vl_inadimpl,
    NULL::numeric   AS pct_yield_mes,
    NULL::numeric   AS captc_mes,
    NULL::numeric   AS resg_mes,
    NULL::numeric   AS vl_ativo,
    NULL::text      AS quota_subclass_id
  FROM cvm_fidc_mensal

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIAGRO: monthly snapshot — same structure as FIDC
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fiagro'        AS entity_type,
    vl_patrim_liq,
    NULL::numeric   AS vl_quota,
    NULL::int       AS nr_cotst,
    vl_inadimpl,
    NULL::numeric   AS pct_yield_mes,
    NULL::numeric   AS captc_mes,
    NULL::numeric   AS resg_mes,
    NULL::numeric   AS vl_ativo,
    NULL::text      AS quota_subclass_id
  FROM cvm_fiagro_mensal
  WHERE cnpj IS NOT NULL

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FII: use doc_subtype = 'complemento' which carries yield, cotistas, vl_ativo.
  -- Fallback to doc_subtype = 'geral' for PL when complemento is absent is handled
  -- downstream — here we surface only complemento rows to avoid duplicates.
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    period,
    'fii'                       AS entity_type,
    vl_patrim_liq,
    NULL::numeric               AS vl_quota,
    nr_cotst,
    NULL::numeric               AS vl_inadimpl,
    pct_dividend_yield_mes      AS pct_yield_mes,
    NULL::numeric               AS captc_mes,
    NULL::numeric               AS resg_mes,
    vl_ativo,
    NULL::text                  AS quota_subclass_id
  FROM cvm_fii_mensal
  WHERE doc_subtype = 'complemento'
    AND cnpj IS NOT NULL

  UNION ALL

  -- -------------------------------------------------------------------------
  -- FIP: yearly grain — period = Dec-31 of the reported year
  -- -------------------------------------------------------------------------
  SELECT
    cnpj,
    make_date(period_year, 12, 31)  AS period,
    'fip'                           AS entity_type,
    vl_patrim_liq,
    NULL::numeric                   AS vl_quota,
    NULL::int                       AS nr_cotst,
    NULL::numeric                   AS vl_inadimpl,
    NULL::numeric                   AS pct_yield_mes,
    NULL::numeric                   AS captc_mes,
    NULL::numeric                   AS resg_mes,
    NULL::numeric                   AS vl_ativo,
    NULL::text                      AS quota_subclass_id
  FROM cvm_fip_periodic
  WHERE cnpj IS NOT NULL
;

-- Primary-key index — enforces uniqueness across the union
CREATE UNIQUE INDEX ix_fact_fund_monthly_pk
  ON fact_fund_monthly (cnpj, period, entity_type);

-- Period-scan index for time-series queries
CREATE INDEX ix_fact_fund_monthly_period
  ON fact_fund_monthly (period);

-- Entity-type filter support
CREATE INDEX ix_fact_fund_monthly_entity
  ON fact_fund_monthly (entity_type, period);

-- -------------------------------------------------------------------------
-- Smoke check
-- EXCEPTION: fund data must exist after smoke tests have been run.
-- -------------------------------------------------------------------------
DO $$
DECLARE
  v_count      BIGINT;
  v_entities   BIGINT;
BEGIN
  SELECT COUNT(*), COUNT(DISTINCT entity_type)
    INTO v_count, v_entities
  FROM fact_fund_monthly;

  IF v_count = 0 THEN
    -- silo.ci_smoke_bypass=on marks a CI compile run against an empty throwaway
    -- Postgres (see 01_dim_fund); production applies never set it.
    IF current_setting('silo.ci_smoke_bypass', true) = 'on' THEN
      RAISE WARNING 'fact_fund_monthly smoke check skipped: 0 rows (silo.ci_smoke_bypass=on)';
      RETURN;
    END IF;
    RAISE EXCEPTION
      'fact_fund_monthly smoke check FAILED: 0 rows — ingest at least one fund type first';
  END IF;

  RAISE NOTICE 'fact_fund_monthly smoke check OK: % rows across % entity type(s)',
    v_count, v_entities;
END $$;

-- ---------------------------------------------------------------------------
-- Period completeness — the single source of the "don't serve incomplete
-- months" rule (dashboard spines, api.panel/api.fund_nav default windows,
-- api.coverage all read this; nothing filters fact_fund_monthly itself, so
-- ops freshness, api.funds.last_period and mv_savings_flow keep seeing the
-- newest partial month).
--
-- A period is COMPLETE when both hold:
--   1. its calendar month has ended (an in-progress month is never complete:
--      FI aggregates daily filings, so mid-month coverage looks full while
--      captc_mes/resg_mes are mechanically month-to-date fractions);
--   2. the number of funds reporting reaches COMPLETENESS_THRESHOLD (0.80)
--      of the median across that entity's prior six periods — CVM's 1-2
--      month publication lag means a month can be over but only fractionally
--      filed, and summing 30% of funds reports 30% of the AUM as if it were
--      the industry.
-- Periods keep each family's raw convention (FI/FII/FIAGRO first-of-month,
-- FIDC month-end, FIP year-end) — consumers date_trunc as needed. The first
-- periods of a family (no trailing window yet) count as complete: they are
-- deep history, and refusing to serve them would hide real published data.
-- This classifies serving readiness only; it never modifies data.
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_period_completeness;
CREATE MATERIALIZED VIEW mv_period_completeness AS
WITH counts AS (
    SELECT entity_type, period, COUNT(DISTINCT cnpj) AS n_funds
    FROM fact_fund_monthly
    GROUP BY entity_type, period
)
SELECT
    c.entity_type,
    c.period,
    c.n_funds,
    m.trailing_median,
    ROUND(c.n_funds::numeric / NULLIF(m.trailing_median, 0), 4) AS coverage_ratio,
    (
        date_trunc('month', c.period) < date_trunc('month', CURRENT_DATE)
        AND COALESCE(
              c.n_funds::numeric >= 0.80 * m.trailing_median,
              TRUE   -- no trailing window yet: deep history, serve it
            )
    ) AS is_complete
FROM counts c
LEFT JOIN LATERAL (
    SELECT (percentile_cont(0.5) WITHIN GROUP (ORDER BY w.n_funds))::numeric
        AS trailing_median
    FROM (
        SELECT p.n_funds
        FROM counts p
        WHERE p.entity_type = c.entity_type AND p.period < c.period
        ORDER BY p.period DESC
        LIMIT 6
    ) w
) m ON TRUE;

CREATE UNIQUE INDEX ix_period_completeness_pk
    ON mv_period_completeness (entity_type, period);

COMMENT ON MATERIALIZED VIEW mv_period_completeness IS
    'Serving-readiness per (entity_type, period): a period is complete when its calendar month ended AND >= 80% of the trailing-6-period median fund count has reported. Drives latest_complete_period(); refreshed daily at 06:35 UTC and on every analytical apply. Classification only — no data is modified or dropped.';

-- The one-call form every consumer uses. NULL entity = the max over families
-- (a spine upper bound for mixed charts; per-family rows still filter by
-- their own family's bound). COALESCE floor: on an empty/cold database the
-- previous calendar month is returned so Evidence spines and CI runs never
-- see NULL (a NULL upper bound would empty a generate_series spine, and a
-- zero-row Evidence source writes a zero-byte parquet that kills the build).
CREATE OR REPLACE FUNCTION latest_complete_period(p_entity_type TEXT DEFAULT NULL)
RETURNS DATE
LANGUAGE sql
STABLE
-- Pins its own search_path: api.* callers run with search_path = '' and that
-- propagates down the call stack, so without this per-function (immutable)
-- pin the unqualified mv_period_completeness reference below would fail at
-- runtime from inside api.panel.
SET search_path = public, pg_temp
AS $$
    SELECT COALESCE(
        (
            SELECT max(pc.period)
            FROM mv_period_completeness pc
            WHERE pc.is_complete
              AND (p_entity_type IS NULL OR pc.entity_type = p_entity_type)
        ),
        (date_trunc('month', CURRENT_DATE) - interval '1 month')::date
    );
$$;

COMMENT ON FUNCTION latest_complete_period(TEXT) IS
    'Latest period classified complete by mv_period_completeness for one entity family (fi|fidc|fii|fip|fiagro), or the max across families when NULL. Falls back to the previous calendar month on a cold database. The dashboard spines and the api.panel/api.fund_nav default windows clamp here.';

GRANT SELECT ON mv_period_completeness TO anon, authenticated;
GRANT EXECUTE ON FUNCTION latest_complete_period(TEXT) TO anon, authenticated;

COMMIT;
