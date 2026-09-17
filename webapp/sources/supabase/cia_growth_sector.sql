-- CVM sector aggregates for the latest fiscal year: median revenue growth, median
-- net margin, and the sector's total revenue.
--
-- This is the unit of comparison on the growth page. Conta 3.01 is sales for an
-- industrial company and intermediation income for a bank, so a cross-sector
-- league table of revenue is meaningless — but a sector's own median growth is
-- exactly what a company should be measured against.
--
-- Median rather than mean throughout, so one outlier does not move the sector.
-- Filing and version conventions are identical to cia_growth_company.sql; see the
-- header there for why the span is pinned to 12 months and why net income reads
-- 3.11 with no 3.09 fallback.
WITH latest_ver AS (
    -- A reapresentação refiles a statement under a higher versao and the old rows
    -- remain, so without this a year can appear twice with two different numbers.
    --
    -- Bounded to the trailing 5 years and to doc_type='dfp' on purpose. Unbounded,
    -- this CTE aggregated every DRE partition back to 2010 (~857k rows, planner
    -- cost 1.33M) to find versions for years the page never displays, which is
    -- why it timed out at the Supabase gateway. 5 years comfortably covers the
    -- newest fiscal year plus the prior one it is compared against.
    SELECT cd_cvm, dt_refer, MAX(versao) AS versao
      FROM cia_account
     WHERE grupo = 'DRE' AND escopo = 'con'
       AND doc_type = 'dfp'
       AND dt_refer >= (CURRENT_DATE - INTERVAL '5 years')
     GROUP BY 1, 2
),
annual AS (
    SELECT
        a.cd_cvm,
        EXTRACT(YEAR FROM a.dt_refer)::int AS fy,
        MAX(a.vl_conta) FILTER (WHERE a.cd_conta = '3.01') AS revenue,
        MAX(a.vl_conta) FILTER (WHERE a.cd_conta = '3.11') AS net_income
      FROM cia_account a
      JOIN latest_ver l
        ON l.cd_cvm = a.cd_cvm
       AND l.dt_refer = a.dt_refer
       AND a.versao IS NOT DISTINCT FROM l.versao
     WHERE a.grupo = 'DRE'
       AND a.escopo = 'con'
       AND a.ordem_exerc = 'ÚLTIMO'
       AND a.doc_type = 'dfp'
       AND a.dt_refer >= (CURRENT_DATE - INTERVAL '5 years')
       AND a.dt_ini_exerc IS NOT NULL
       AND a.dt_fim_exerc IS NOT NULL
       AND (EXTRACT(YEAR  FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc)) * 12
          + EXTRACT(MONTH FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc))) = 12
       AND a.cd_conta IN ('3.01', '3.11')
     GROUP BY 1, 2
),
paired AS (
    SELECT
        cd_cvm, fy, revenue, net_income,
        LAG(revenue) OVER (PARTITION BY cd_cvm ORDER BY fy) AS prev_revenue,
        LAG(fy)      OVER (PARTITION BY cd_cvm ORDER BY fy) AS prev_fy
      FROM annual
),
scoped AS (
    SELECT
        p.cd_cvm,
        COALESCE(c.setor, 'Não informado') AS setor,
        p.fy,
        p.revenue / 1e6 AS revenue_mm,
        ROUND(100.0 * (p.revenue / p.prev_revenue - 1), 1) AS rev_growth_pct,
        CASE WHEN p.revenue > 0
             THEN ROUND(100.0 * p.net_income / p.revenue, 1) END AS net_margin_pct
      FROM paired p
      JOIN cia_company c ON c.cd_cvm = p.cd_cvm
     WHERE p.prev_fy = p.fy - 1
       AND p.prev_revenue >= 100000000
       AND p.revenue IS NOT NULL
),
newest AS (
    -- NOT MAX(fy). A fiscal year exists in this table the moment its first filer
    -- reports, and CVM's filing calendar is not synchronised: companies with a
    -- non-calendar fiscal year (the sugar and ethanol names file April-March)
    -- land a whole year ahead of everyone else. Measured 2026-09-17: fiscal 2026
    -- had 8 filers against fiscal 2025's 438. MAX(fy) therefore pinned this entire
    -- page to those 8 -- 6 of which survived the floor, all in one sector -- so
    -- the sector chart showed a single bar and every table showed one sector.
    --
    -- So: the newest fiscal year that is actually filed broadly enough to be a
    -- cross-section. The threshold is not delicate; a filed year carries several
    -- hundred comparable companies and a year in progress carries single digits,
    -- two orders of magnitude apart. Companies whose newest filing is the excluded
    -- year still appear, on their prior year, so nobody is dropped -- they are
    -- just compared on the same basis as their peers.
    SELECT MAX(fy) AS fy
      FROM (SELECT fy FROM scoped GROUP BY fy HAVING COUNT(*) >= 50) filed
)
SELECT
    s.setor,
    s.fy,
    COUNT(*) AS peers,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.rev_growth_pct)::numeric, 1)
        AS median_growth_pct,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.net_margin_pct)::numeric, 1)
        AS median_margin_pct,
    ROUND(SUM(s.revenue_mm)::numeric, 0) AS sector_revenue_mm
  FROM scoped s
  JOIN newest n ON s.fy = n.fy
 GROUP BY 1, 2
HAVING COUNT(*) >= 5
 ORDER BY median_growth_pct DESC NULLS LAST
