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
-- 30min: the build is single-threaded and (since #207) one pass over
-- cvm_fi_diario. LOCAL so a pooler that ignores session SET still honours it
-- inside this transaction.
SET LOCAL statement_timeout = '30min';

-- WHY THIS BUILD IS SINGLE-THREADED, ONE-PASS, AND JIT-OFF (2026-09-01).
--
-- The CREATE MATERIALIZED VIEW below had been killing its client connection
-- on every apply since at least 2026-08-30. psql saw only:
--
--     server closed the connection unexpectedly
--     psql:.../04_fact_fund_monthly.sql:NNN: error: connection to server was lost
--
-- Because the whole file is one transaction (BEGIN here, COMMIT at the end),
-- the DROP rolled back with it, so fact_fund_monthly kept its previous
-- contents. Nothing was lost — but nothing was refreshed either.
--
-- Two different things have produced that same psql symptom, and they need
-- opposite treatment.
--
-- MEMORY (#175). Two applies of identical code over identical data died 61s
-- apart (5m23.5s, 4m22.7s) with statement_timeout at 15min. Under a Gather
-- each of the FI branch's sorts gets its own work_mem PER WORKER. Turning
-- the workers off (and JIT off: compiling this query spikes memory on a
-- small instance) bounds the peak. Daily CVM Ingest #205 then succeeded.
--
-- POOLER IDLE DROP (#207, run 33535880218, SHA 5a338b7 — the #177 merge).
-- #177's FIP de-dup made the CREATE correct, and it no longer died on
-- ix_fact_fund_monthly_pk. The next analytics-only apply then failed:
--
--     04  died 4m44s  connection lost at the CREATE's closing semicolon
--     05  died 4m43s  connection lost (CREATE of an 8-second matview)
--     07  died 4m43s  connection lost (CREATE VIEW — not a scan)
--     09  died 32s    statement_timeout, CONTEXT SQL function fund_profile
--     11  died 4m44s  connection lost (CREATE INDEX)
--     12–19 ok
--
-- 07 is catalog DDL. It cannot OOM for 4m44s; it waits. The 4m44s is the
-- session-pooler idle cap (CI uses aws-*.pooler.supabase.com:5432; see
-- .env.example). The pooler dropped the client while the backend kept
-- AccessExclusiveLock from DROP MATERIALIZED VIEW CASCADE, so 05/07/11
-- waited until their own sockets were dropped and 09's 30s timeout fired
-- planning fund_profile against the locked relation.
--
-- #206 (pre-#177) finished this CREATE and failed on the unique index in
-- 5m03s — just inside the cap. #177 added a DISTINCT ON + GROUP BY on FIP
-- and the CREATE no longer returned before the pooler cut the wire.
--
-- Two changes, both required. apply_analytical.sh now sends the same TCP
-- keepalives as pg_client.py so the pooler sees traffic during a quiet
-- CREATE. The FI branch below is one scan of cvm_fi_diario instead of two,
-- so the exclusive lock is held for one sort rather than two.
--
-- LOCAL, so they revert at COMMIT and touch nothing else in the session.
SET LOCAL max_parallel_workers_per_gather = 0;
SET LOCAL jit = off;

DROP MATERIALIZED VIEW IF EXISTS fact_fund_monthly CASCADE;

CREATE MATERIALIZED VIEW fact_fund_monthly AS

WITH fi_per_subclass AS MATERIALIZED (
  -- ONE scan of cvm_fi_diario. Window sums give fund-month flows over every
  -- daily row (including days whose PL is null); DISTINCT ON then keeps the
  -- last day that actually carries PL, matching the old snapshot filter.
  -- captc_mes/resg_mes are already at fund-month grain on every subclass
  -- row — fi_monthly must MAX them, never SUM, or two subclasses would
  -- double-count the same inflows.
  SELECT DISTINCT ON (cnpj, id_subclasse, period)
    cnpj,
    id_subclasse,
    period,
    vl_patrim_liq,
    vl_quota,
    nr_cotst,
    captc_mes,
    resg_mes
  FROM (
    SELECT
      d.cnpj,
      d.id_subclasse,
      date_trunc('month', d.dt_comptc)::date AS period,
      d.dt_comptc,
      d.vl_patrim_liq,
      d.vl_quota,
      d.nr_cotst,
      SUM(d.captc_dia) OVER (
        PARTITION BY d.cnpj, date_trunc('month', d.dt_comptc)
      ) AS captc_mes,
      SUM(d.resg_dia) OVER (
        PARTITION BY d.cnpj, date_trunc('month', d.dt_comptc)
      ) AS resg_mes
    FROM cvm_fi_diario d
    WHERE NOT EXISTS (SELECT 1 FROM cvm_etf_registry e WHERE e.cnpj = d.cnpj)
  ) scanned
  WHERE vl_patrim_liq IS NOT NULL
  ORDER BY
    cnpj,
    id_subclasse,
    period,
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
    MAX(p.captc_mes)                                                    AS captc_mes,
    MAX(p.resg_mes)                                                     AS resg_mes,
    MAX(q.id_subclasse)                                                 AS quota_subclass_id
  FROM fi_per_subclass p
  LEFT JOIN fi_quota_subclass q USING (cnpj)
  GROUP BY p.cnpj, p.period
)

  -- -------------------------------------------------------------------------
  -- FI: daily → monthly aggregation
  -- Last-day-of-month PL / cotistas summed to a per-fund total. Quota follows
  -- the stable subclass selected above. Flows are the fund-month window sums
  -- from the single scan (every day, including null-PL days).
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
    last_day.captc_mes,
    last_day.resg_mes,
    NULL::numeric                                    AS vl_ativo,
    last_day.quota_subclass_id
  FROM fi_monthly last_day

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
  --
  -- ONE ROW PER (fund, year), and it takes work to get there. This branch used
  -- to select cvm_fip_periodic straight, which was unique per fund-year only
  -- because the OLD key discarded everything else: the table keyed on
  -- (cnpj, doc_type, period_year), so a yearly archive that carries every
  -- period of the year kept one filing and overwrote the rest — 72-77% of each
  -- file. Migration 34 rekeyed it on the filing's own DT_COMPTC plus
  -- classe_cota, and once the backfill restored those rows this branch emitted
  -- several per fund-year and ix_fact_fund_monthly_pk could not be built:
  --
  --     ERROR: could not create unique index "ix_fact_fund_monthly_pk"
  --     DETAIL: Key (cnpj, period, entity_type)
  --             = (49930492000103, 2024-12-31, fip) is duplicated.
  --
  -- Two different things multiply the rows, and they need opposite treatment.
  --
  -- SEVERAL PERIODS IN ONE YEAR are successive observations of the same fund,
  -- so exactly one belongs at a Dec-31 annual grain: the latest. Summing them
  -- would add a fund's Q1 net assets to its Q4 net assets and report the total
  -- as year-end AUM.
  --
  -- SEVERAL CLASSES AT ONE PERIOD are parts of one fund, so they are additive —
  -- the same rule the FI branch above applies to subclasses, for the same
  -- reason. Picking one class instead would report a share class's net assets
  -- as the whole fund's.
  --
  -- Hence: latest filing PER CLASS, then sum across classes. DISTINCT ON also
  -- settles doc_type deterministically, so a fund filing under two document
  -- types in one period contributes once rather than twice.
  --
  -- The year bucket stays period_year rather than EXTRACT(YEAR FROM period):
  -- migration 34 deliberately leaves period NULL on rows whose DT_COMPTC could
  -- not be recovered rather than deleting published data, and those rows still
  -- belong to their archive year. NULLS LAST keeps them from winning the
  -- DISTINCT ON over a row that does carry a date.
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
  FROM (
    SELECT cnpj,
           period_year,
           sum(vl_patrim_liq) AS vl_patrim_liq
      FROM (
        SELECT DISTINCT ON (cnpj, period_year, classe_cota)
               cnpj,
               period_year,
               classe_cota,
               vl_patrim_liq
          FROM cvm_fip_periodic
         WHERE cnpj IS NOT NULL
           AND period_year IS NOT NULL
         ORDER BY cnpj, period_year, classe_cota, period DESC NULLS LAST, doc_type
      ) latest_filing_per_class
     GROUP BY cnpj, period_year
  ) fip_year
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
