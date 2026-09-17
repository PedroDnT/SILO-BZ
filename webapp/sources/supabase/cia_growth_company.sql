-- Year-over-year revenue growth and margin movement per listed company, with the
-- company's rank inside its CVM sector and its distance from the sector median.
--
-- ANNUAL ONLY, deliberately. An ITR prints each account twice under one dt_refer —
-- once for the 3-month span and once year-to-date — separated only by
-- dt_ini_exerc. Pinning doc_type='dfp' AND a 12-month span makes every pair
-- like-for-like; mixing a quarter with a year-to-date figure is the most common way
-- to produce a confidently wrong series.
--
-- Net income is conta 3.11 ONLY. There is no 3.09 fallback here: 3.09 is profit
-- BEFORE statutory profit-sharing (3.10), so substituting it overstates net income
-- by the participations line. A filer that did not report 3.11 shows null.
--
-- Revenue (3.01) is NOT comparable across sectors — it is sales for an industrial
-- company and intermediation income for a bank. Every rank below is therefore
-- within setor, and vs_setor_pp is the column that matters.
WITH latest_ver AS (
    -- A reapresentação refiles a statement under a higher versao and the old rows
    -- remain, so without this a year can appear twice with two different numbers.
    SELECT cd_cvm, dt_refer, MAX(versao) AS versao
      FROM cia_account
     WHERE grupo = 'DRE' AND escopo = 'con'
     GROUP BY 1, 2
),
annual AS (
    SELECT
        a.cd_cvm,
        a.dt_refer,
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
       -- Accented, verbatim from the latin-1 source. 'ULTIMO' matches zero rows.
       AND a.ordem_exerc = 'ÚLTIMO'
       AND a.doc_type = 'dfp'
       AND a.dt_ini_exerc IS NOT NULL
       AND a.dt_fim_exerc IS NOT NULL
       AND (EXTRACT(YEAR  FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc)) * 12
          + EXTRACT(MONTH FROM AGE(a.dt_fim_exerc + 1, a.dt_ini_exerc))) = 12
       AND a.cd_conta IN ('3.01', '3.11')
     GROUP BY 1, 2, 3
),
paired AS (
    SELECT
        cd_cvm, fy, revenue, net_income,
        LAG(revenue)    OVER (PARTITION BY cd_cvm ORDER BY fy) AS prev_revenue,
        LAG(net_income) OVER (PARTITION BY cd_cvm ORDER BY fy) AS prev_net_income,
        LAG(fy)         OVER (PARTITION BY cd_cvm ORDER BY fy) AS prev_fy
      FROM annual
),
scoped AS (
    -- Consecutive years only (prev_fy = fy - 1 rejects a gap year), a positive
    -- prior-year denominator, and a size floor. The floor is not cosmetic: a
    -- company going from R$1mm to R$3mm posts 200% growth and would otherwise own
    -- every leaderboard on the page.
    SELECT
        p.cd_cvm,
        c.denom_cia AS company,
        COALESCE(c.setor, 'Não informado') AS setor,
        p.fy,
        p.revenue    / 1e6 AS revenue_mm,
        p.net_income / 1e6 AS net_income_mm,
        ROUND(100.0 * (p.revenue / p.prev_revenue - 1), 1) AS rev_growth_pct,
        CASE WHEN p.revenue > 0
             THEN ROUND(100.0 * p.net_income / p.revenue, 1) END AS net_margin_pct,
        CASE WHEN p.revenue > 0 AND p.prev_net_income IS NOT NULL
             THEN ROUND(100.0 * p.net_income      / p.revenue
                      - 100.0 * p.prev_net_income / p.prev_revenue, 1)
             END AS margin_change_pp
      FROM paired p
      JOIN cia_company c ON c.cd_cvm = p.cd_cvm
     WHERE p.prev_fy = p.fy - 1
       AND p.prev_revenue >= 100000000
       AND p.revenue IS NOT NULL
),
newest AS (
    SELECT MAX(fy) AS fy FROM scoped
),
current_fy AS (
    SELECT s.* FROM scoped s JOIN newest n ON s.fy = n.fy
),
sector_med AS (
    -- peers >= 5 is a small-n guard: a median over three companies is not a market
    -- view, and a rank within it is noise. Companies in thinner sectors still
    -- appear, with a null sector median.
    SELECT
        setor,
        COUNT(*) AS peers_in_setor,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rev_growth_pct)::numeric, 1)
            AS setor_median_growth_pct
      FROM current_fy
     GROUP BY 1
    HAVING COUNT(*) >= 5
)
SELECT
    f.cd_cvm,
    f.company,
    f.setor,
    f.fy,
    f.revenue_mm,
    f.net_income_mm,
    f.rev_growth_pct,
    f.net_margin_pct,
    f.margin_change_pp,
    m.peers_in_setor,
    m.setor_median_growth_pct,
    ROUND(f.rev_growth_pct - m.setor_median_growth_pct, 1) AS vs_setor_pp,
    RANK() OVER (PARTITION BY f.setor ORDER BY f.rev_growth_pct DESC) AS rank_in_setor
  FROM current_fy f
  LEFT JOIN sector_med m ON m.setor = f.setor
 ORDER BY f.setor, rank_in_setor
