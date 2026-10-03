-- Portfolio diagnosis phase 0: measurements for docs/reference/research/portfolio-diagnosis-phase0.md
--
-- Read-only diagnostics for Supabase Postgres 17. Runs under
-- `psql -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on"
--       -c "SET statement_timeout = '90s'" -f <this file>`
-- from .github/workflows/health.yml mode=diagnostics, or by hand in the
-- Supabase MCP. Plain SQL only: no psql meta-commands, no DDL, no temp tables,
-- no writes. Every statement is bounded by a period/date predicate and/or a
-- LIMIT so it fits the 90 s budget.
--
-- Big-table rules this file obeys: cvm_fi_diario is partitioned by year and
-- BRIN on dt_comptc, so every read names a dt_comptc window. cvm_fi_cda_acoes
-- (12 GB) and cvm_fi_cda_cotas (10 GB) have NO period-only index; they are
-- reached only through uq_fi_cda_acoes / uq_fi_cda_cotas (cnpj, period, ...),
-- idx_fi_cda_acoes_ativo (cd_ativo, period DESC) and idx_fi_cda_cotas_held
-- (cnpj_cota, period DESC), always at ONE period and for a handful of CNPJs.
-- Month totals come from the matviews fact_fund_monthly, dim_fund and
-- mv_fund_holdings_monthly where they fit.
--
-- The api.* functions refuse with 22023 above one 1,000-row page, and the cap
-- is asserted INSIDE the function (LIMIT 1001 -> api.assert_row_cap), so an
-- outer LIMIT does not prevent it. Under ON_ERROR_STOP a refusal aborts the
-- rest of the file, which is why every api.* call sits at the END (Q15c, Q16)
-- and is ordered safest first.

-- ---------------------------------------------------------------------------
-- [Q1] pg_trgm installed, version and schema (report item: name resolver).
--      The schema matters: Q3 calls similarity() unqualified and relies on the
--      role's search_path reaching it (Supabase installs extensions in
--      `extensions`; migration 24 ran CREATE EXTENSION IF NOT EXISTS pg_trgm).
-- ---------------------------------------------------------------------------
SELECT 'Q1' AS q,
       extname,
       extversion,
       extnamespace::regnamespace AS ext_schema
  FROM pg_extension
 WHERE extname = 'pg_trgm';

-- ---------------------------------------------------------------------------
-- [Q2] Renamed funds since 2024: CNPJs with >= 2 distinct DENOM_SOCIAL in
--      cvm_fi_cda_fund_name (one row per fund, month and name; migration 60),
--      ranked by the latest FI NAV in fact_fund_monthly (report item: renames).
-- ---------------------------------------------------------------------------
WITH names AS (
    SELECT cnpj, period, denom_social
      FROM cvm_fi_cda_fund_name
     WHERE period >= DATE '2024-01-01'
), renamed AS (
    SELECT cnpj,
           count(DISTINCT denom_social) AS n_names,
           min(period)                  AS first_period,
           max(period)                  AS last_period
      FROM names
     GROUP BY cnpj
    HAVING count(DISTINCT denom_social) >= 2
), nav AS (
    SELECT DISTINCT ON (f.cnpj) f.cnpj, f.period, f.vl_patrim_liq
      FROM fact_fund_monthly f
      JOIN renamed r USING (cnpj)
     WHERE f.entity_type = 'fi'
       AND f.period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '6 months')::date
       AND f.vl_patrim_liq IS NOT NULL
     ORDER BY f.cnpj, f.period DESC
)
SELECT 'Q2' AS q,
       r.cnpj,
       r.n_names,
       r.first_period,
       r.last_period,
       (SELECT n.denom_social FROM names n
         WHERE n.cnpj = r.cnpj ORDER BY n.period ASC,  n.denom_social LIMIT 1) AS oldest_name,
       (SELECT n.denom_social FROM names n
         WHERE n.cnpj = r.cnpj ORDER BY n.period DESC, n.denom_social LIMIT 1) AS newest_name,
       nav.period                            AS nav_period,
       round(nav.vl_patrim_liq / 1e6, 1)     AS nav_mm,
       (SELECT count(*) FROM renamed)        AS renamed_funds_total
  FROM renamed r
  LEFT JOIN nav USING (cnpj)
 ORDER BY nav.vl_patrim_liq DESC NULLS LAST, r.cnpj
 LIMIT 10;

-- ---------------------------------------------------------------------------
-- [Q3] Resolver test on the Q2 ten: for each fund's OLDEST name, rank every
--      CURRENT name (one per CNPJ at the latest cvm_fi_cda_fund_name period)
--      by similarity(old, current). Reports the rank of the true CNPJ and the
--      top-1 minus top-2 gap; ambiguous when the gap is < 0.05 (report item:
--      name resolver). The candidate universe is the latest period only.
--      similarity() is deliberately unqualified (see Q1). If Q1 shows no
--      pg_trgm, this statement fails and ON_ERROR_STOP ends the file here.
-- ---------------------------------------------------------------------------
WITH names AS (
    SELECT cnpj, period, denom_social
      FROM cvm_fi_cda_fund_name
     WHERE period >= DATE '2024-01-01'
), renamed AS (
    SELECT cnpj
      FROM names
     GROUP BY cnpj
    HAVING count(DISTINCT denom_social) >= 2
), nav AS (
    SELECT DISTINCT ON (f.cnpj) f.cnpj, f.vl_patrim_liq
      FROM fact_fund_monthly f
      JOIN renamed r USING (cnpj)
     WHERE f.entity_type = 'fi'
       AND f.period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '6 months')::date
       AND f.vl_patrim_liq IS NOT NULL
     ORDER BY f.cnpj, f.period DESC
), targets AS (
    SELECT r.cnpj,
           (SELECT n.denom_social FROM names n
             WHERE n.cnpj = r.cnpj ORDER BY n.period ASC, n.denom_social LIMIT 1) AS old_name
      FROM renamed r
      LEFT JOIN nav USING (cnpj)
     ORDER BY nav.vl_patrim_liq DESC NULLS LAST, r.cnpj
     LIMIT 10
), latest AS (
    SELECT max(period) AS p FROM cvm_fi_cda_fund_name
), cands AS (
    SELECT DISTINCT ON (n.cnpj) n.cnpj, n.denom_social
      FROM cvm_fi_cda_fund_name n, latest
     WHERE n.period = latest.p
     ORDER BY n.cnpj, n.denom_social
), scored AS (
    SELECT t.cnpj                                   AS target_cnpj,
           t.old_name,
           c.cnpj                                   AS cand_cnpj,
           c.denom_social                           AS cand_name,
           similarity(t.old_name, c.denom_social)   AS sim,
           row_number() OVER (PARTITION BY t.cnpj
                              ORDER BY similarity(t.old_name, c.denom_social) DESC, c.cnpj) AS rk
      FROM targets t
     CROSS JOIN cands c
)
SELECT 'Q3' AS q,
       s.target_cnpj,
       left(s.old_name, 60)                                           AS old_name,
       (SELECT x.rk FROM scored x
         WHERE x.target_cnpj = s.target_cnpj AND x.cand_cnpj = s.target_cnpj) AS true_rank,
       max(s.cand_cnpj) FILTER (WHERE s.rk = 1)                       AS top1_cnpj,
       left(max(s.cand_name) FILTER (WHERE s.rk = 1), 60)             AS top1_name,
       round((max(s.sim) FILTER (WHERE s.rk = 1))::numeric, 4)        AS top1_sim,
       round((max(s.sim) FILTER (WHERE s.rk = 2))::numeric, 4)        AS top2_sim,
       round((max(s.sim) FILTER (WHERE s.rk = 1)
            - max(s.sim) FILTER (WHERE s.rk = 2))::numeric, 4)        AS gap,
       (max(s.sim) FILTER (WHERE s.rk = 1)
        - max(s.sim) FILTER (WHERE s.rk = 2)) < 0.05                  AS ambiguous,
       (SELECT count(*) FROM cands)                                   AS n_candidates,
       (SELECT p FROM latest)                                         AS candidate_period
  FROM scored s
 GROUP BY s.target_cnpj, s.old_name
 ORDER BY s.target_cnpj
 LIMIT 10;

-- ---------------------------------------------------------------------------
-- [Q4] XP Bancos tie-break: the latest 5 daily rows per (cnpj, id_subclasse)
--      for the two candidate CNPJs, within the last 30 days so the read prunes
--      to the current partition (report item: duplicate-name tie-break).
-- ---------------------------------------------------------------------------
SELECT 'Q4' AS q,
       cnpj,
       id_subclasse,
       dt_comptc,
       vl_quota,
       vl_patrim_liq,
       nr_cotst
  FROM (
    SELECT d.cnpj, d.id_subclasse, d.dt_comptc, d.vl_quota, d.vl_patrim_liq, d.nr_cotst,
           row_number() OVER (PARTITION BY d.cnpj, d.id_subclasse ORDER BY d.dt_comptc DESC) AS rn
      FROM cvm_fi_diario d
     WHERE d.cnpj IN ('35377390000106', '50088190000119')
       AND d.dt_comptc >= CURRENT_DATE - 30
  ) x
 WHERE rn <= 5
 ORDER BY cnpj, id_subclasse, dt_comptc DESC
 LIMIT 20;

-- ---------------------------------------------------------------------------
-- [Q5] Fee conversion on the 3 largest funds (by NAV) that filed
--      vl_taxa_administracao in BOTH of the latest two balancete months
--      (report item: fee from the balancete).
--      The fee accounts accumulate from each fund's own fiscal-year start and
--      are negative (COFI group 8), so the monthly flow is this month minus
--      last month; annualised = -flow * 12 / avg(NAV) where NAV =
--      vl_patrimonio_sem_resultado + vl_receitas + vl_despesas (migration 61).
--      CAVEAT: in the fund's fiscal-year reset month the accumulator restarts,
--      the subtraction is wrong once a year, and the sign flips; reset_suspect
--      flags that (the accumulated negative became less negative).
--      Compared with cvm_fund_registry.raw->>'TAXA_ADM' (the residual of the
--      legacy cad_fi.csv; NULL when the row came from registro_fundo_classe
--      with another key - see Q5b) and cvm_etf_registry.taxa_adm.
-- ---------------------------------------------------------------------------
WITH months AS (
    SELECT max(dt_comptc) AS cur FROM cvm_fi_balancete_resumo
), prev_m AS (
    SELECT max(b.dt_comptc) AS prev
      FROM cvm_fi_balancete_resumo b, months
     WHERE b.dt_comptc < months.cur
), cur AS (
    SELECT b.* FROM cvm_fi_balancete_resumo b, months
     WHERE b.dt_comptc = months.cur AND b.vl_taxa_administracao IS NOT NULL
), prev AS (
    SELECT b.* FROM cvm_fi_balancete_resumo b, prev_m
     WHERE b.dt_comptc = prev_m.prev AND b.vl_taxa_administracao IS NOT NULL
), pairs AS (
    SELECT c.cnpj,
           c.dt_comptc                                            AS cur_month,
           p.dt_comptc                                            AS prev_month,
           p.vl_taxa_administracao                                AS fee_acc_prev,
           c.vl_taxa_administracao                                AS fee_acc_cur,
           c.vl_taxa_administracao - p.vl_taxa_administracao      AS fee_flow,
           c.vl_patrimonio_sem_resultado + c.vl_receitas + c.vl_despesas AS nav_cur,
           p.vl_patrimonio_sem_resultado + p.vl_receitas + p.vl_despesas AS nav_prev
      FROM cur c
      JOIN prev p USING (cnpj)
), top3 AS (
    SELECT * FROM pairs
     WHERE nav_cur IS NOT NULL AND nav_prev IS NOT NULL AND nav_cur > 0
     ORDER BY nav_cur DESC
     LIMIT 3
)
SELECT 'Q5' AS q,
       t.cnpj,
       left(r.fund_name, 50)                                        AS fund_name,
       t.prev_month,
       t.cur_month,
       t.fee_acc_prev,
       t.fee_acc_cur,
       t.fee_flow,
       round(t.nav_cur / 1e6, 1)                                    AS nav_cur_mm,
       round((-t.fee_flow * 12) / NULLIF((t.nav_cur + t.nav_prev) / 2, 0) * 100, 4)
                                                                    AS fee_annualised_pct,
       (t.fee_flow > 0)                                             AS reset_suspect,
       r.raw ->> 'TAXA_ADM'                                         AS registry_taxa_adm,
       e.taxa_adm                                                   AS etf_taxa_adm
  FROM top3 t
  LEFT JOIN cvm_fund_registry r
         ON r.cnpj = t.cnpj AND r.entity_type = 'fi'
  LEFT JOIN LATERAL (
        SELECT min(x.taxa_adm) AS taxa_adm
          FROM cvm_etf_registry x
         WHERE x.cnpj = t.cnpj
  ) e ON TRUE
 ORDER BY t.nav_cur DESC;

-- [Q5b] Which fee-like keys the registry residual actually carries for those 3
--       CNPJs (every entity_type row), so the owner sees the real key name when
--       TAXA_ADM above is NULL.
WITH months AS (
    SELECT max(dt_comptc) AS cur FROM cvm_fi_balancete_resumo
), prev_m AS (
    SELECT max(b.dt_comptc) AS prev
      FROM cvm_fi_balancete_resumo b, months
     WHERE b.dt_comptc < months.cur
), cur AS (
    SELECT b.* FROM cvm_fi_balancete_resumo b, months
     WHERE b.dt_comptc = months.cur AND b.vl_taxa_administracao IS NOT NULL
), prev AS (
    SELECT b.* FROM cvm_fi_balancete_resumo b, prev_m
     WHERE b.dt_comptc = prev_m.prev AND b.vl_taxa_administracao IS NOT NULL
), top3 AS (
    SELECT c.cnpj,
           c.vl_patrimonio_sem_resultado + c.vl_receitas + c.vl_despesas AS nav_cur
      FROM cur c
      JOIN prev p USING (cnpj)
     WHERE c.vl_patrimonio_sem_resultado + c.vl_receitas + c.vl_despesas > 0
       AND p.vl_patrimonio_sem_resultado + p.vl_receitas + p.vl_despesas IS NOT NULL
     ORDER BY 2 DESC
     LIMIT 3
)
SELECT 'Q5b' AS q,
       r.cnpj,
       r.entity_type,
       k.key                               AS raw_key,
       left(r.raw ->> k.key, 40)           AS raw_value
  FROM top3 t
  JOIN cvm_fund_registry r ON r.cnpj = t.cnpj
 CROSS JOIN LATERAL jsonb_object_keys(COALESCE(r.raw, '{}'::jsonb)) AS k(key)
 WHERE k.key ILIKE '%tax%'
 ORDER BY r.cnpj, r.entity_type, k.key
 LIMIT 30;

-- ---------------------------------------------------------------------------
-- [Q6] Look-through depth for 3 retail FICs (report item: look-through).
--      Period: the month in the last 6 whose quota-kind total in
--      mv_fund_holdings_monthly has the most filing funds (the newest months
--      are incomplete). Roots: among the 300 FI funds with the most
--      quotaholders in fact_fund_monthly at that period, the 3 largest that
--      hold fund quotas (probe through uq_fi_cda_cotas (cnpj, period, ...);
--      the table has no period-only index, so roots are NOT chosen by
--      scanning cvm_fi_cda_cotas, and the probe is capped at 300 CNPJs).
--      Recursion cnpj -> cnpj_cota at that one period, depth <= 6, with the
--      PG14+ CYCLE clause as the cycle guard (path array kept by Postgres).
--      A leaf is a held fund with no block-2 row of its own at that period
--      (it holds no quotas, or filed no CDA). Fan-out from a big FoF can push
--      this toward the 90 s timeout; the depth cap is the safety valve.
-- ---------------------------------------------------------------------------
WITH RECURSIVE p AS (
    SELECT period
      FROM mv_fund_holdings_monthly
     WHERE kind = 'quota' AND key IS NULL
       AND period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '6 months')::date
     ORDER BY n_funds DESC, period DESC
     LIMIT 1
), candidates AS (
    -- Bounded BEFORE the probe: Postgres filters, then sorts, then limits, so
    -- an EXISTS in the same query level would run once per FI fund at P (tens
    -- of thousands of index probes into a 10 GB table) before LIMIT 3 could
    -- stop anything, and a statement timeout here is an ERROR that ends the
    -- file under ON_ERROR_STOP. 300 funds by quotaholders is enough: a retail
    -- FIC with fund-quota holdings is in the top 300 by nr_cotst.
    SELECT f.cnpj, f.nr_cotst, f.vl_patrim_liq
      FROM fact_fund_monthly f, p
     WHERE f.entity_type = 'fi'
       AND f.period = p.period
       AND f.nr_cotst IS NOT NULL
     ORDER BY f.nr_cotst DESC, f.cnpj
     LIMIT 300
), roots AS (
    SELECT k.cnpj, k.nr_cotst, k.vl_patrim_liq
      FROM candidates k, p
     WHERE EXISTS (SELECT 1 FROM cvm_fi_cda_cotas c
                    WHERE c.cnpj = k.cnpj AND c.period = p.period
                      AND c.tp_aplic ILIKE 'Cotas de Fundos%')
     ORDER BY k.nr_cotst DESC, k.cnpj
     LIMIT 3
), tree AS (
    SELECT r.cnpj            AS root,
           r.cnpj            AS holder,
           c.cnpj_cota       AS held,
           1                 AS depth,
           c.vl_merc_pos_final AS v
      FROM roots r
      JOIN cvm_fi_cda_cotas c ON c.cnpj = r.cnpj
      CROSS JOIN p
     WHERE c.period = p.period
    UNION ALL
    SELECT t.root,
           t.held,
           c.cnpj_cota,
           t.depth + 1,
           c.vl_merc_pos_final
      FROM tree t
      JOIN cvm_fi_cda_cotas c ON c.cnpj = t.held
      CROSS JOIN p
     WHERE c.period = p.period
       AND t.depth < 6
) CYCLE held SET is_cycle USING path
, nodes AS (
    -- Columns named one by one: `t.*` does NOT expand the CYCLE-generated
    -- is_cycle / path columns (verified on PG16), so a star here loses them.
    SELECT t.root, t.holder, t.held, t.depth, t.v, t.is_cycle, t.path,
           NOT EXISTS (SELECT 1 FROM cvm_fi_cda_cotas c, p
                        WHERE c.cnpj = t.held AND c.period = p.period) AS is_leaf
      FROM tree t
)
SELECT 'Q6' AS q,
       (SELECT period FROM p)                                   AS period,
       n.root,
       (SELECT r.nr_cotst FROM roots r WHERE r.cnpj = n.root)   AS root_quotaholders,
       round((SELECT r.vl_patrim_liq FROM roots r WHERE r.cnpj = n.root) / 1e6, 1) AS root_nav_mm,
       max(n.depth)                                             AS max_depth,
       count(*)                                                 AS n_edges,
       count(DISTINCT n.held)                                   AS n_distinct_held,
       count(DISTINCT n.held) FILTER (WHERE n.is_leaf)          AS n_leaf_funds,
       count(*) FILTER (WHERE n.is_cycle)                       AS n_cycles,
       count(*) FILTER (WHERE n.depth = 6 AND NOT n.is_leaf)    AS n_truncated_at_depth_6
  FROM nodes n
 GROUP BY n.root
 ORDER BY n.root
 LIMIT 3;

-- ---------------------------------------------------------------------------
-- [Q7] 2026 FIDC restatement pairs with diffs (report item: restatements).
--      [Q7a] pairs by status where the diff ran in 2026 or the restated
--      document was delivered in 2026 (migration 46 statuses).
-- ---------------------------------------------------------------------------
SELECT 'Q7a' AS q,
       p.status,
       count(*)                                        AS pairs,
       count(*) FILTER (WHERE p.n_changed > 0)         AS pairs_with_changes,
       count(DISTINCT p.cnpj)                          AS funds,
       min(p.compared_at)::date                        AS first_compared,
       max(p.compared_at)::date                        AS last_compared
  FROM fnet_document_pair p
  JOIN fnet_document d ON d.fnet_id = p.fnet_id
 WHERE p.compared_at >= TIMESTAMPTZ '2026-01-01'
    OR d.delivered_at >= TIMESTAMP '2026-01-01'
 GROUP BY p.status
 ORDER BY pairs DESC
 LIMIT 20;

-- [Q7b] Of the compared 2026 pairs, how many changed a delinquency or NAV leaf
--       (VL_CRED_EXISTE_INAD, VL_PATRIM_LIQ, VL_INAD_*) with both numbers parsed.
WITH pairs26 AS (
    SELECT p.fnet_id, p.prev_fnet_id, p.cnpj
      FROM fnet_document_pair p
      JOIN fnet_document d ON d.fnet_id = p.fnet_id
     WHERE p.status = 'compared'
       AND (p.compared_at >= TIMESTAMPTZ '2026-01-01'
            OR d.delivered_at >= TIMESTAMP '2026-01-01')
), hits AS (
    SELECT x.fnet_id, x.prev_fnet_id, x.cnpj, f.leaf, f.old_num, f.new_num, f.match_basis
      FROM pairs26 x
      JOIN fnet_document_diff f
        ON f.fnet_id = x.fnet_id AND f.prev_fnet_id = x.prev_fnet_id
     WHERE (f.leaf IN ('VL_CRED_EXISTE_INAD', 'VL_PATRIM_LIQ') OR f.leaf LIKE 'VL\_INAD\_%')
       AND f.old_num IS NOT NULL
       AND f.new_num IS NOT NULL
)
SELECT 'Q7b' AS q,
       (SELECT count(*) FROM pairs26)                          AS compared_pairs_2026,
       count(DISTINCT (fnet_id, prev_fnet_id))                 AS pairs_with_delinq_or_nav_diff,
       count(DISTINCT cnpj)                                    AS funds,
       count(*)                                                AS diff_rows,
       count(*) FILTER (WHERE match_basis = 'position')        AS diff_rows_position_matched
  FROM hits;

-- [Q7c] Sample of those diffs: cnpj, leaf, old and new numbers.
WITH pairs26 AS (
    SELECT p.fnet_id, p.prev_fnet_id, p.cnpj, p.compared_at
      FROM fnet_document_pair p
      JOIN fnet_document d ON d.fnet_id = p.fnet_id
     WHERE p.status = 'compared'
       AND (p.compared_at >= TIMESTAMPTZ '2026-01-01'
            OR d.delivered_at >= TIMESTAMP '2026-01-01')
)
SELECT 'Q7c' AS q,
       x.cnpj,
       x.fnet_id,
       x.prev_fnet_id,
       f.leaf,
       f.change_kind,
       f.match_basis,
       f.old_num,
       f.new_num,
       round(100.0 * (f.new_num - f.old_num) / NULLIF(f.old_num, 0), 1) AS pct_change
  FROM pairs26 x
  JOIN fnet_document_diff f
    ON f.fnet_id = x.fnet_id AND f.prev_fnet_id = x.prev_fnet_id
 WHERE (f.leaf IN ('VL_CRED_EXISTE_INAD', 'VL_PATRIM_LIQ') OR f.leaf LIKE 'VL\_INAD\_%')
   AND f.old_num IS NOT NULL
   AND f.new_num IS NOT NULL
 ORDER BY x.compared_at DESC, x.fnet_id, f.leaf
 LIMIT 50;

-- [Q7d] Which leaf names the 2026 compared pairs actually changed, most
--       frequent first. Makes a Q7b zero interpretable: CVM's CSV headers and
--       FNET's XML tags are not guaranteed to share names, so the VL_INAD_%
--       / VL_CRED_EXISTE_INAD / VL_PATRIM_LIQ pattern above may simply not be
--       how the XML spells them.
WITH pairs26 AS (
    SELECT p.fnet_id, p.prev_fnet_id
      FROM fnet_document_pair p
      JOIN fnet_document d ON d.fnet_id = p.fnet_id
     WHERE p.status = 'compared'
       AND (p.compared_at >= TIMESTAMPTZ '2026-01-01'
            OR d.delivered_at >= TIMESTAMP '2026-01-01')
)
SELECT 'Q7d' AS q,
       f.block,
       f.leaf,
       count(*)                                                  AS diff_rows,
       count(DISTINCT (f.fnet_id, f.prev_fnet_id))               AS pairs,
       count(*) FILTER (WHERE f.old_num IS NOT NULL AND f.new_num IS NOT NULL) AS numeric_rows
  FROM pairs26 x
  JOIN fnet_document_diff f
    ON f.fnet_id = x.fnet_id AND f.prev_fnet_id = x.prev_fnet_id
 GROUP BY f.block, f.leaf
 ORDER BY diff_rows DESC, f.block, f.leaf
 LIMIT 30;

-- ---------------------------------------------------------------------------
-- [Q8] 60-month coverage: funds with >= 60 months of a month-end quota in the
--      last 61 months, by entity_type (report item: history depth). Only the
--      FI branch of fact_fund_monthly carries vl_quota (04_fact_fund_monthly),
--      so a parallel NAV-month count is reported for the other families; FIP
--      is yearly (Dec-31 rows) and can never reach 60.
-- ---------------------------------------------------------------------------
WITH w AS (
    SELECT (date_trunc('month', CURRENT_DATE) - INTERVAL '61 months')::date AS from_p
), per_fund AS (
    SELECT f.cnpj,
           f.entity_type,
           count(*) FILTER (WHERE f.vl_quota IS NOT NULL AND f.vl_quota > 0) AS quota_months,
           count(*) FILTER (WHERE f.vl_patrim_liq IS NOT NULL)               AS nav_months
      FROM fact_fund_monthly f, w
     WHERE f.period >= w.from_p
     GROUP BY f.cnpj, f.entity_type
)
SELECT 'Q8' AS q,
       (SELECT from_p FROM w)                                   AS window_from,
       entity_type,
       count(*)                                                 AS funds,
       count(*) FILTER (WHERE quota_months >= 60)               AS funds_60m_quota,
       count(*) FILTER (WHERE nav_months >= 60)                 AS funds_60m_nav,
       count(*) FILTER (WHERE quota_months BETWEEN 36 AND 59)   AS funds_36_59m_quota
  FROM per_fund
 GROUP BY entity_type
 ORDER BY entity_type
 LIMIT 10;

-- ---------------------------------------------------------------------------
-- [Q9] cvm_fi_perfil fill rates at the latest two periods (the newest month
--      can be partial); columns lifted by migration 14 (report item: perfil).
-- ---------------------------------------------------------------------------
WITH lp AS (
    SELECT max(period) AS p FROM cvm_fi_perfil
)
SELECT 'Q9' AS q,
       f.period,
       count(*)                                          AS rows_total,
       count(f.pr_ativo_cred_priv)                       AS n_pr_ativo_cred_priv,
       count(f.nr_dia_cinqu_perc)                        AS n_nr_dia_cinqu_perc,
       count(f.nr_dia_cem_perc)                          AS n_nr_dia_cem_perc,
       count(f.st_liqdez)                                AS n_st_liqdez,
       count(f.pr_patrim_liq_convtd_caixa)               AS n_pr_patrim_liq_convtd_caixa,
       round(100.0 * count(f.pr_ativo_cred_priv) / count(*), 1)        AS pct_cred_priv,
       round(100.0 * count(f.nr_dia_cinqu_perc) / count(*), 1)         AS pct_dia_cinqu,
       round(100.0 * count(f.st_liqdez) / count(*), 1)                 AS pct_st_liqdez,
       round(100.0 * count(f.pr_patrim_liq_convtd_caixa) / count(*), 1) AS pct_convtd_caixa
  FROM cvm_fi_perfil f, lp
 WHERE f.period >= (lp.p - INTERVAL '1 month')::date
 GROUP BY f.period
 ORDER BY f.period DESC
 LIMIT 2;

-- ---------------------------------------------------------------------------
-- [Q10] Block 4 vs block 6 debentures per month since 2025-01 (report item:
--       where fund debentures live). Block 4 from the matview's debenture-kind
--       month total (key IS NULL); block 6 from cvm_fi_cda_debentures itself
--       (small table).
-- ---------------------------------------------------------------------------
SELECT 'Q10a' AS q, period, 'block4_matview' AS source,
       n_funds, n_assets, round(vl_total / 1e9, 2) AS vl_bn
  FROM mv_fund_holdings_monthly
 WHERE kind = 'debenture' AND key IS NULL AND period >= DATE '2025-01-01'
UNION ALL
SELECT 'Q10a', period, 'block6_table',
       count(DISTINCT cnpj), count(DISTINCT cpf_cnpj_emissor), round(sum(vl_merc_pos_final) / 1e9, 2)
  FROM cvm_fi_cda_debentures
 WHERE period >= DATE '2025-01-01'
 GROUP BY period
 ORDER BY period, source
 LIMIT 60;

-- [Q10b] Share of block-4 debenture issuer codes (ISIN chars 3-6, the matview
--        key) that match a listed company's ISIN stem in dim_ticker_float
--        (ISIN from b3_instrument_registry, cash equities), at the latest
--        complete debenture period: by key count and by value.
WITH p AS (
    SELECT period
      FROM mv_fund_holdings_monthly
     WHERE kind = 'debenture' AND key IS NULL
       AND period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '12 months')::date
     ORDER BY n_funds DESC, period DESC
     LIMIT 1
), issuers AS (
    SELECT m.key, m.n_funds, m.vl_total
      FROM mv_fund_holdings_monthly m, p
     WHERE m.kind = 'debenture' AND m.key IS NOT NULL AND m.period = p.period
), listed AS (
    SELECT DISTINCT substring(isin FROM 3 FOR 4) AS stem
      FROM dim_ticker_float
     WHERE isin IS NOT NULL AND length(isin) >= 6
)
SELECT 'Q10b' AS q,
       (SELECT period FROM p)                                     AS period,
       count(*)                                                   AS issuer_codes,
       count(l.stem)                                              AS codes_matching_listed,
       round(100.0 * count(l.stem) / NULLIF(count(*), 0), 1)      AS pct_codes_listed,
       round(sum(i.vl_total) / 1e9, 2)                            AS vl_bn_total,
       round(100.0 * sum(i.vl_total) FILTER (WHERE l.stem IS NOT NULL)
             / NULLIF(sum(i.vl_total), 0), 1)                     AS pct_value_listed,
       (SELECT count(*) FROM listed)                              AS listed_stems
  FROM issuers i
  LEFT JOIN listed l ON l.stem = i.key;

-- ---------------------------------------------------------------------------
-- [Q11] Block 6 indexer values since 2025-01 (report item: debenture indexers).
-- ---------------------------------------------------------------------------
SELECT 'Q11' AS q,
       cd_indexador_posfx,
       ds_indexador_posfx,
       count(*)                                  AS rows_total,
       count(DISTINCT cnpj)                      AS funds,
       round(sum(vl_merc_pos_final) / 1e9, 3)    AS vl_bn
  FROM cvm_fi_cda_debentures
 WHERE period >= DATE '2025-01-01'
 GROUP BY cd_indexador_posfx, ds_indexador_posfx
 ORDER BY sum(vl_merc_pos_final) DESC NULLS LAST
 LIMIT 30;

-- ---------------------------------------------------------------------------
-- [Q12] CRI/CRA rating text (report item: ratings).
--       [Q12a] top 50 classificacao_risco_atual values since 2025-01.
-- ---------------------------------------------------------------------------
SELECT 'Q12a' AS q,
       instrument_type,
       classificacao_risco_atual,
       count(*)                                   AS rows_total,
       count(DISTINCT codigo_identificacao)       AS instruments
  FROM cvm_securit_serie
 WHERE data_referencia >= DATE '2025-01-01'
 GROUP BY instrument_type, classificacao_risco_atual
 ORDER BY rows_total DESC
 LIMIT 50;

-- [Q12b] FNET documents whose type or species mentions a rating, by categoria.
--        fnet_document has no trigram index, so the ILIKE scan is bounded to
--        deliveries since 2024-01-01 (idx_fnet_document_delivered).
SELECT 'Q12b' AS q,
       categoria,
       tipo_documento,
       count(*)                     AS documents,
       min(delivered_at)::date      AS first_delivery,
       max(delivered_at)::date      AS last_delivery
  FROM fnet_document
 WHERE delivered_at >= TIMESTAMP '2024-01-01'
   AND (tipo_documento ILIKE '%rating%'
        OR tipo_documento ILIKE '%agência%'
        OR tipo_documento ILIKE '%classificação de risco%'
        OR especie ILIKE '%rating%'
        OR especie ILIKE '%agência%'
        OR especie ILIKE '%classificação de risco%')
 GROUP BY categoria, tipo_documento
 ORDER BY documents DESC
 LIMIT 20;

-- ---------------------------------------------------------------------------
-- [Q13] Regulation documents in FNET by categoria and delivery year, since
--       2019-01-01 (report item: regulamentos).
-- ---------------------------------------------------------------------------
SELECT 'Q13' AS q,
       categoria,
       extract(year FROM delivered_at)::int   AS delivery_year,
       count(*)                               AS documents,
       count(*) FILTER (WHERE versao > 1)     AS restated
  FROM fnet_document
 WHERE delivered_at >= TIMESTAMP '2019-01-01'
   AND tipo_documento ILIKE '%regulamento%'
 GROUP BY categoria, extract(year FROM delivered_at)
 ORDER BY delivery_year DESC, documents DESC
 LIMIT 30;

-- ---------------------------------------------------------------------------
-- [Q14] Anon / authenticated privileges on public relations WITHOUT RLS
--       (report item: exposure). has_table_privilege is wrapped in CASE so a
--       database with no anon role (a local throwaway) returns NULL instead
--       of aborting the file. Readable-by-anon rows sort first.
-- ---------------------------------------------------------------------------
SELECT 'Q14a' AS q,
       c.relname,
       c.relkind,
       c.relrowsecurity,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
            THEN has_table_privilege('anon', c.oid, 'SELECT') END          AS anon_select,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
            THEN has_table_privilege('authenticated', c.oid, 'SELECT') END AS authenticated_select
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
   AND NOT c.relrowsecurity
 ORDER BY anon_select DESC NULLS LAST, authenticated_select DESC NULLS LAST, c.relname
 LIMIT 100;

-- [Q14b] The same, summarised.
SELECT 'Q14b' AS q,
       c.relkind,
       c.relrowsecurity,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
            THEN has_table_privilege('anon', c.oid, 'SELECT') END          AS anon_select,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
            THEN has_table_privilege('authenticated', c.oid, 'SELECT') END AS authenticated_select,
       count(*)                                                            AS relations
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
 GROUP BY 2, 3, 4, 5
 ORDER BY 2, 3, 4, 5
 LIMIT 40;

-- [Q14c] Schema USAGE for anon on public and api.
SELECT 'Q14c' AS q,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
            THEN has_schema_privilege('anon', 'public', 'USAGE') END AS anon_usage_public,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
             AND EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'api')
            THEN has_schema_privilege('anon', 'api', 'USAGE') END    AS anon_usage_api,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
            THEN has_schema_privilege('authenticated', 'public', 'USAGE') END AS authenticated_usage_public;

-- ---------------------------------------------------------------------------
-- [Q15] Demo-portfolio candidates (report item: demo portfolio).
--       [Q15a] the 5 largest block-4 PETR4 positions at the latest complete
--       stock period of the matview, through idx_fi_cda_acoes_ativo
--       (cd_ativo, period DESC), with the filing name from
--       cvm_fi_cda_fund_name and the fund's NAV / quotaholders.
-- ---------------------------------------------------------------------------
WITH p AS (
    SELECT period
      FROM mv_fund_holdings_monthly
     WHERE kind = 'stock' AND key IS NULL
       AND period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '6 months')::date
     ORDER BY n_funds DESC, period DESC
     LIMIT 1
)
SELECT 'Q15a' AS q,
       a.period,
       a.cnpj,
       left(n.denom_social, 60)                      AS denom_social,
       round(sum(a.vl_merc_pos_final) / 1e6, 1)      AS petr4_value_mm,
       sum(a.qt_pos_final)                           AS petr4_qty,
       round(f.vl_patrim_liq / 1e6, 1)               AS nav_mm,
       f.nr_cotst,
       round(100.0 * sum(a.vl_merc_pos_final) / NULLIF(f.vl_patrim_liq, 0), 2) AS petr4_pct_nav
  FROM cvm_fi_cda_acoes a
  JOIN p ON a.period = p.period
  LEFT JOIN LATERAL (
        SELECT x.denom_social FROM cvm_fi_cda_fund_name x
         WHERE x.cnpj = a.cnpj AND x.period = a.period
         ORDER BY x.denom_social LIMIT 1
  ) n ON TRUE
  LEFT JOIN fact_fund_monthly f
         ON f.cnpj = a.cnpj AND f.period = a.period AND f.entity_type = 'fi'
 WHERE a.cd_ativo = 'PETR4'
 GROUP BY a.period, a.cnpj, n.denom_social, f.vl_patrim_liq, f.nr_cotst
 ORDER BY sum(a.vl_merc_pos_final) DESC
 LIMIT 5;

-- [Q15b] Two FICs holding the same master with the largest combined value at
--        that period. BOUNDED VARIANT: the "20 most-held masters" are the most
--        held AMONG the quota rows of the 50 largest PETR4 holders from Q15a
--        (reached through uq_fi_cda_cotas (cnpj, period, ...)), and their
--        holders are reached through idx_fi_cda_cotas_held (cnpj_cota, period
--        DESC), top 50 holders per master. A market-wide "most-held" rank
--        needs a period scan of the 10 GB table and would time out.
WITH p AS (
    SELECT period
      FROM mv_fund_holdings_monthly
     WHERE kind = 'stock' AND key IS NULL
       AND period >= (date_trunc('month', CURRENT_DATE) - INTERVAL '6 months')::date
     ORDER BY n_funds DESC, period DESC
     LIMIT 1
), holders AS (
    SELECT a.cnpj
      FROM cvm_fi_cda_acoes a, p
     WHERE a.cd_ativo = 'PETR4' AND a.period = p.period
     GROUP BY a.cnpj
     ORDER BY sum(a.vl_merc_pos_final) DESC
     LIMIT 50
), masters AS (
    SELECT c.cnpj_cota, sum(c.vl_merc_pos_final) AS v
      FROM cvm_fi_cda_cotas c
      JOIN holders h ON c.cnpj = h.cnpj
      CROSS JOIN p
     WHERE c.period = p.period
     GROUP BY c.cnpj_cota
     ORDER BY v DESC
     LIMIT 20
), holdings AS (
    SELECT *
      FROM (
        SELECT c.cnpj_cota,
               c.cnpj,
               max(c.nm_fundo_cota)        AS master_name,
               sum(c.vl_merc_pos_final)    AS v,
               row_number() OVER (PARTITION BY c.cnpj_cota ORDER BY sum(c.vl_merc_pos_final) DESC) AS rn
          FROM cvm_fi_cda_cotas c
          JOIN masters m ON m.cnpj_cota = c.cnpj_cota
          CROSS JOIN p
         WHERE c.period = p.period
         GROUP BY c.cnpj_cota, c.cnpj
      ) x
     WHERE rn <= 50
), pairs AS (
    SELECT a.cnpj_cota,
           a.master_name,
           a.cnpj          AS fic_a,
           b.cnpj          AS fic_b,
           a.v             AS value_a,
           b.v             AS value_b,
           a.v + b.v       AS combined
      FROM holdings a
      JOIN holdings b ON b.cnpj_cota = a.cnpj_cota AND a.cnpj < b.cnpj
)
SELECT 'Q15b' AS q,
       (SELECT period FROM p)                 AS period,
       pr.cnpj_cota                           AS master_cnpj,
       left(pr.master_name, 50)               AS master_name,
       pr.fic_a,
       left(na.denom_social, 45)              AS fic_a_name,
       round(pr.value_a / 1e6, 1)             AS value_a_mm,
       pr.fic_b,
       left(nb.denom_social, 45)              AS fic_b_name,
       round(pr.value_b / 1e6, 1)             AS value_b_mm,
       round(pr.combined / 1e6, 1)            AS combined_mm
  FROM pairs pr
  LEFT JOIN LATERAL (
        SELECT x.denom_social FROM cvm_fi_cda_fund_name x, p
         WHERE x.cnpj = pr.fic_a AND x.period = p.period ORDER BY x.denom_social LIMIT 1
  ) na ON TRUE
  LEFT JOIN LATERAL (
        SELECT x.denom_social FROM cvm_fi_cda_fund_name x, p
         WHERE x.cnpj = pr.fic_b AND x.period = p.period ORDER BY x.denom_social LIMIT 1
  ) nb ON TRUE
 ORDER BY pr.combined DESC
 LIMIT 5;

-- [Q15c] Restatements of the two candidate FIDCs since 2026-01-01 through the
--        served function. Signature confirmed in 24_api_fnet.sql:
--        api.fund_restatements(p_cnpj TEXT, p_from DATE, p_to DATE,
--        p_tipo_fundo TEXT). One fund's 2026 restatements will not reach the
--        1,000-row cap; if one did, the 22023 refusal would end the file here,
--        which is why this sits after Q1-Q15b.
SELECT 'Q15c' AS q,
       r.cnpj, r.tipo_fundo, left(r.fund_name, 40) AS fund_name,
       r.tipo_documento, r.reference_raw, r.versao, r.modalidade,
       r.delivered_at, r.previous_fnet_id, r.lag_days,
       r.n_fields_changed, r.diff_status
  FROM api.fund_restatements('57833038000162', DATE '2026-01-01', NULL, NULL) r
 ORDER BY r.delivered_at DESC
 LIMIT 20;

SELECT 'Q15c' AS q,
       r.cnpj, r.tipo_fundo, left(r.fund_name, 40) AS fund_name,
       r.tipo_documento, r.reference_raw, r.versao, r.modalidade,
       r.delivered_at, r.previous_fnet_id, r.lag_days,
       r.n_fields_changed, r.diff_status
  FROM api.fund_restatements('45829761000199', DATE '2026-01-01', NULL, NULL) r
 ORDER BY r.delivered_at DESC
 LIMIT 20;

-- ---------------------------------------------------------------------------
-- [Q16] Screens shape (report item: screens). LAST ON PURPOSE: every api.screen_*
--       wrapper refuses with 22023 above 1,000 rows and the cap is asserted
--       inside the function, so the outer LIMIT 3 only shortens the printout;
--       a refusal under ON_ERROR_STOP aborts whatever follows. Calls are
--       ordered safest first. Signatures confirmed in 23_api_screens.sql and
--       25_api_filing_screens.sql; arguments are the dashboard defaults.
--       Two deliberate deviations from the literal ask:
--         * screen_delinquency_drivers gets p_driver = 'consistent_worsening'
--           (every FIDC with >= 6 observations gets a row otherwise, 'stable'
--           included - documented as exceeding a page);
--         * the dormant COUNT comes from public.fraud_screen_dormant_funds(3),
--           the un-capped source the wrapper reads (parked_capital alone was
--           8,257 rows in the 2026-09-02 diagnostic, so
--           count(*) FROM api.screen_dormant_funds(3) is a guaranteed 22023);
--           the wrapper is then sampled with narrowing arguments, last.
-- ---------------------------------------------------------------------------
SELECT 'Q16 overdue_securit' AS q, s.instrument_type, s.securitizer_cnpj, s.instrument_code,
       s.maturity, s.status, s.volume_mm, s.rating, s.screen
  FROM api.screen_overdue_securit(1e5) s
 ORDER BY s.volume_mm DESC NULLS LAST
 LIMIT 3;

SELECT 'Q16 zombie_growth' AS q, s.cnpj, left(s.fund_name, 40) AS fund_name, s.period,
       s.nav_mm, s.delinquency_pct, s.screen
  FROM api.screen_zombie_growth(NULL, 5, 1e6) s
 ORDER BY s.nav_mm DESC NULLS LAST
 LIMIT 3;

SELECT 'Q16 evergreen_aging' AS q, s.cnpj, left(s.fund_name, 40) AS fund_name,
       s.months_observed, s.min_longtail_pct, s.max_longtail_pct, s.screen
  FROM api.screen_evergreen_aging(12, 70, 10) s
 ORDER BY s.max_longtail_pct DESC NULLS LAST
 LIMIT 3;

SELECT 'Q16 captive_vehicles' AS q, s.cnpj, left(s.fund_name, 40) AS fund_name,
       s.latest_period, s.max_nav_mm, s.min_quotaholders, s.screen
  FROM api.screen_captive_vehicles(3, 10, 5e7) s
 ORDER BY s.max_nav_mm DESC NULLS LAST
 LIMIT 3;

SELECT 'Q16 restatements' AS q, s.cnpj, s.tipo_fundo, left(s.fund_name, 40) AS fund_name,
       s.window_from, s.window_to, s.documents, s.restatements,
       s.restatements_re, s.restatements_rc, s.restatement_pct, s.last_restated_at, s.screen
  FROM api.screen_restatements(12, NULL, 3, 20, NULL) s
 ORDER BY s.restatements DESC, s.cnpj
 LIMIT 3;

SELECT 'Q16 delinquency_drivers' AS q, s.cnpj, left(s.fund_name, 40) AS fund_name, s.status,
       s.window_from, s.window_to, s.n_months, s.delinquency_start, s.delinquency_end,
       s.delta_brl, s.rate_start, s.rate_end, s.delta_pp, s.driver, s.screen
  FROM api.screen_delinquency_drivers(NULL, 12, 6, 1e6, 1.0, 'consistent_worsening') s
 ORDER BY s.delta_brl DESC NULLS LAST
 LIMIT 3;

-- The dormant count, from the un-capped public screen the wrapper reads
-- (diagnostics run as the database owner, so the client-role REVOKE in
-- 15_fraud_screens.sql does not apply here).
SELECT 'Q16 dormant_funds count' AS q,
       d.dormancy,
       count(*)                           AS classes,
       round(sum(d.last_pl) / 1e9, 2)     AS last_nav_bn,
       min(d.window_from)                 AS window_from,
       max(d.window_to)                   AS window_to
  FROM public.fraud_screen_dormant_funds(3) d
 GROUP BY d.dormancy
 ORDER BY classes DESC
 LIMIT 5;

-- Narrowed so the wrapper stays under its page: empty shells with NAV >= R$10mm.
SELECT 'Q16 dormant_funds sample' AS q, s.cnpj, left(s.fund_name, 40) AS fund_name,
       left(s.administrator, 30) AS administrator, s.window_from, s.window_to,
       s.months_observed, s.max_quotaholders, s.last_nav, s.dormancy, s.screen
  FROM api.screen_dormant_funds(3, 'empty_shell', 1e7) s
 ORDER BY s.last_nav DESC NULLS LAST
 LIMIT 3;
