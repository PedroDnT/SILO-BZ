-- D2.2 ETF fundamentals available WITHOUT the scrape
SELECT count(*) AS etfs,
  count(taxa_adm)      AS with_taxa_adm,
  count(vl_patrim_liq) AS with_nav,
  count(gestor)        AS with_gestor,
  count(dt_patrim_liq) AS with_nav_date
  FROM cvm_etf_registry;
