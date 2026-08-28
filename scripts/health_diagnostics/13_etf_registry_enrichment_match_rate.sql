-- D2.2b why only 8 of 187 ETFs carry a manager / NAV / fee
-- cvm_etf_registry is a curated ticker->CNPJ seed enriched from cad_fi by CNPJ
-- (src/pipeline/ingest_etf.py). Measured 2026-08-28: 187 ETFs, 8 with gestor,
-- 8 with vl_patrim_liq, ZERO with taxa_adm — so the enrichment is matching
-- almost nothing and the ETF page has to fall back to B3 prices alone.
--
-- The suspected cause is the CVM-175 split: the seed carries the FUND-level
-- CNPJ while post-175 registration is per SHARE CLASS, with a different CNPJ.
-- This measures that instead of assuming it: how many ETF CNPJs appear in the
-- fund registry at all, and whether the ones that do are the ones enriched.
SELECT
  count(*)                                                      AS etfs,
  count(*) FILTER (WHERE r.cnpj IS NOT NULL)                    AS cnpj_in_fund_registry,
  count(*) FILTER (WHERE e.gestor IS NOT NULL)                  AS with_gestor,
  count(*) FILTER (WHERE e.taxa_adm IS NOT NULL)                AS with_taxa_adm,
  count(*) FILTER (WHERE e.vl_patrim_liq IS NOT NULL)           AS with_nav,
  -- The diagnostic question: enriched but NOT in the registry, or in the
  -- registry but NOT enriched? The second means a matching bug; the first
  -- means the registry is not the source the enrichment actually used.
  count(*) FILTER (WHERE r.cnpj IS NOT NULL AND e.gestor IS NULL) AS registry_hit_but_unenriched,
  count(*) FILTER (WHERE r.cnpj IS NULL AND e.gestor IS NOT NULL) AS enriched_without_registry_row
FROM cvm_etf_registry e
LEFT JOIN cvm_fund_registry r ON r.cnpj = e.cnpj;

-- Do the ETF CNPJs show up anywhere else we hold fund identity? If the daily
-- FI file knows them, the enrichment can read from there instead of cad_fi.
SELECT
  count(*)                                                   AS etfs,
  count(*) FILTER (WHERE d.cnpj IS NOT NULL)                 AS known_to_dim_fund,
  count(*) FILTER (WHERE f.cnpj IS NOT NULL)                 AS has_monthly_facts
FROM cvm_etf_registry e
LEFT JOIN LATERAL (SELECT 1 AS cnpj FROM dim_fund d WHERE d.cnpj = e.cnpj LIMIT 1) d ON TRUE
LEFT JOIN LATERAL (SELECT 1 AS cnpj FROM fact_fund_monthly f WHERE f.cnpj = e.cnpj LIMIT 1) f ON TRUE;

-- A sample of the unenriched ones, to eyeball the CNPJs against CVM's site.
SELECT ticker, cnpj, fund_name, provider, situacao, is_active
  FROM cvm_etf_registry
 WHERE gestor IS NULL
 ORDER BY ticker
 LIMIT 15;
