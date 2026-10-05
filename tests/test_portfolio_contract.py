"""The portfolio-diagnosis reads in schema `api` (31_api_portfolio.sql, catalog v51; v54 adds portfolio_movement; v62 portfolio_instruments and portfolio_fund_terms).

Offline: the SQL text, the catalog and the CI wiring are pinned to each other.
The behaviour itself is executed in tests/sql/portfolio_behaviour.sql (CI's
sql-compile job). What this file keeps true (map #510, docs/reference/research/
portfolio-diagnosis-phase0.md):

* the house serving rules: SECURITY DEFINER with an empty pinned search_path,
  REVOKE from PUBLIC then GRANT to anon / authenticated / silo_api, one page plus
  one row and api.assert_row_cap refusing above it, nothing trimmed;
* no read of a big CDA table that is not driven from the CNPJ set and one period;
* the resolver normalises case and accents only (no unaccent), searches the whole
  name history, and never infers an indexer, sector or economic group;
* the fee estimate and the disclosed fee are different columns, and the estimate
  says it is one;
* the file is applied after the files it needs, and the behaviour test is wired
  into CI beside the other tests/sql files.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL31 = (ANALYTICAL / "31_api_portfolio.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

SIGNATURES = {
    "portfolio_resolve": "api.portfolio_resolve(TEXT[], TEXT[], NUMERIC[], DATE[])",
    "portfolio_fees": "api.portfolio_fees(TEXT[], DATE)",
    "portfolio_lookthrough": "api.portfolio_lookthrough(TEXT[], DATE, INT)",
    "portfolio_movement": "api.portfolio_movement(TEXT[], DATE)",
    "portfolio_instruments": "api.portfolio_instruments(TEXT[])",
    "portfolio_fund_terms": "api.portfolio_fund_terms(TEXT[])",
    "portfolio_fee_peers": "api.portfolio_fee_peers(TEXT[], DATE)",
}


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function(name: str) -> str:
    start = SQL31.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    return SQL31[start: SQL31.index("$fn$;", SQL31.index("AS $fn$", start)) + 5]


def test_file_is_one_guarded_transaction_after_its_inputs():
    body = _strip(SQL31)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    for needed in ("04_fact_fund_monthly.sql", "19_api_contract.sql", "30_fund_holdings.sql"):
        assert ordered.index("31_api_portfolio.sql") > ordered.index(needed)


def test_exactly_the_seven_api_functions_are_created():
    created = re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL31))
    assert created == [
        "portfolio_resolve", "portfolio_fees", "portfolio_lookthrough", "portfolio_movement",
        "portfolio_instruments", "portfolio_fund_terms", "portfolio_fee_peers",
    ]


def test_definer_empty_search_path_and_grants():
    flat = re.sub(r"\s+", " ", SQL31)
    for name, sig in SIGNATURES.items():
        head = _function(name)
        head = head[: head.index("AS $fn$")]
        assert "SECURITY DEFINER" in head and "SET search_path = ''" in head, name
        assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in flat, name
        assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in flat, name
        assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in flat, name


def test_every_function_refuses_above_one_page_and_never_trims():
    for name in SIGNATURES:
        body = _strip(_function(name))
        assert "LIMIT 1001" in body, f"{name} must fetch one page plus one row"
        assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body, name
        assert "ERRCODE = '22023'" in body or "assert_row_cap" in body, name
    # The over-cap hint names the real lever, not a window these functions do not have.
    helper = _strip(SQL19[SQL19.index("FUNCTION api.assert_row_cap"):SQL19.index("COMMENT ON FUNCTION api.assert_row_cap")])
    assert "p_fn = 'portfolio_resolve'" in helper
    assert re.search(
        r"\('portfolio_fees', 'portfolio_lookthrough', 'portfolio_movement',\s*'portfolio_fund_terms', 'portfolio_fee_peers'\)",
        helper,
    )
    assert "p_fn = 'portfolio_instruments'" in helper
    portfolio_hint = helper[helper.index("p_fn = 'portfolio_resolve'"): helper.index("left(p_fn, 7) = 'screen_'")]
    assert "p_from" not in portfolio_hint and "p_after" not in portfolio_hint


def test_calls_are_capped_and_refused_with_a_why_and_a_how():
    for name in SIGNATURES:
        body = _function(name)
        assert "more than 200" in body, f"{name} caps the call at 200 lines or CNPJs"
    # The refusals the caller can fix carry both halves in the message itself.
    assert body.count("To fix") >= 1
    assert "To fix" in _function("portfolio_resolve") and "To fix" in _function("portfolio_fees")


def test_big_cda_tables_are_read_by_cnpj_and_one_period_only():
    body = re.sub(r"'[^']*'", "''", _strip(_function("portfolio_lookthrough")))
    for table in ("cvm_fi_cda", "cvm_fi_cda_cotas", "cvm_fi_cda_acoes", "cvm_fi_cda_debentures"):
        for m in re.finditer(rf"public\.{table}\s+(\w+)", body):
            alias = m.group(1)
            window = body[m.end(): m.end() + 260]
            assert re.search(rf"\b{alias}\.cnpj\s*=", window), f"{table} read without a cnpj key"
            assert re.search(rf"\b{alias}\.period\s*=\s*v_period", window), f"{table} read without one period"


def test_lookthrough_follows_quotas_with_a_cycle_guard_and_a_depth_cap():
    body = _strip(_function("portfolio_lookthrough"))
    assert "WITH RECURSIVE" in body
    assert re.search(r"\)\s*CYCLE\s+held\s+SET\s+is_cycle\s+USING", body)
    assert "t.depth < p_max_depth" in body
    assert "p_max_depth < 1 OR p_max_depth > 6" in body
    # Repo collateral is not a holding of the bond.
    assert "'Operações Compromissadas' THEN 'repo'" in body
    assert "'Títulos Públicos' THEN 'government_bond'" in body
    # The debenture's issuer is the ISIN code, never a CNPJ; a CPF is never a CNPJ.
    assert "substring(x.cd_isin FROM 3 FOR 4)" in body
    assert "upper(btrim(x.pf_pj_emissor)) = 'PJ'" in body
    # NAV is the monthly fact, not the CDA blocks' own total.
    assert "public.fact_fund_monthly" in body


def test_default_month_follows_the_holdings_completeness_rule():
    body = _strip(_function("portfolio_lookthrough"))
    assert "public.mv_fund_holdings_monthly" in body
    assert "h.kind = 'quota' AND h.key IS NULL" in body
    assert "m.n_funds >= 0.9 *" in body
    assert "percentile_cont(0.5)" in body and "INTERVAL '12 months'" in body


def test_resolver_normalises_case_and_accents_only_and_searches_the_history():
    body = _strip(SQL31)
    assert "unaccent" not in body.lower(), "unaccent is not installed on Supabase"
    norm = body[body.index("FUNCTION public.fund_name_norm"): body.index("COMMENT ON FUNCTION public.fund_name_norm")]
    assert "translate(" in norm and "lower(" in norm
    assert "regexp_replace" in norm
    matview = body[body.index("CREATE MATERIALIZED VIEW public.mv_fund_name_history"): body.index("CREATE UNIQUE INDEX ix_mv_fund_name_history_pk")]
    assert "public.cvm_fi_cda_fund_name" in matview and "public.cvm_fund_registry" in matview
    assert "gist_trgm_ops" in body
    assert "REVOKE ALL ON public.mv_fund_name_history FROM PUBLIC, anon, authenticated;" in body
    fn = _strip(_function("portfolio_resolve"))
    for kind in ("'cnpj'", "'exact_current'", "'exact_history'", "'trigram'"):
        assert kind in fn
    assert "d.dt_comptc = l.qd" in fn, "the quota is read on its exact date, never carried"
    assert "< 0.05" in fn and "<= 0.005" in fn
    assert "k.score >= 0.25" in fn


def test_nothing_is_inferred_from_a_name():
    body = _strip(SQL31).lower()
    for forbidden in ("sector", "setor", "economic_group", "emissor_ligado", "ilike"):
        assert forbidden not in body.replace("tp_ativo", ""), forbidden


def test_fees_keep_the_estimate_and_the_disclosed_fee_apart():
    fn = _function("portfolio_fees")
    out = fn[fn.index("RETURNS TABLE"): fn.index("LANGUAGE plpgsql")]
    for col in (
        "adm_fee_flow", "adm_fee_pct_annual_est", "perf_fee_flow", "perf_fee_pct_annual_est",
        "fiscal_reset_suspect", "disclosed_taxa_adm", "disclosed_taxa_perfm", "disclosed_source",
        "disclosed_as_of", "estimate_label",
    ):
        assert re.search(rf"\b{col}\b", out), col
    body = _strip(fn)
    assert "FROM public.vw_fi_lamina_latest" in body and "to_regclass('public.vw_fi_lamina_latest')" in body
    assert "public.cvm_fund_registry" in body and "public.cvm_fi_balancete_resumo" in body
    # Previous minus current: the accumulated fee is negative, a cost is positive.
    assert "a.adm_prev - a.adm_acc" in body
    assert "a.adm_acc > a.adm_prev" in body, "the reset month is flagged, not subtracted"
    assert "estimate from the balancete accruals" in fn and "not the disclosed fee" in fn
    assert "not a zero fee" in fn


def test_catalog_v51_publishes_the_three_functions_as_raise_only():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 51
    payload = catalog_payload()
    page = payload["limits"]["page"]
    for name in SIGNATURES:
        assert name in page["all"]
        assert name in page["functions"]["raise_only"]
        assert name not in page["functions"]["paged"]
        assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"


def test_behaviour_test_is_wired_into_ci():
    assert "psql \"$POSTGRES_URL\" -v ON_ERROR_STOP=1 -f tests/sql/portfolio_behaviour.sql" in WORKFLOW
    assert (ROOT / "tests" / "sql" / "portfolio_behaviour.sql").is_file()


# --- catalog v52: the Extrato first (map #510; owner decision on issue #515) -----

# The 21 columns v51 shipped, in order. v52 appends after estimate_label and never
# renames, retypes or reorders these (the engine reads them by name).
V51_COLUMNS = [
    "cnpj", "fund_name", "month", "nav", "adm_fee_flow", "adm_fee_pct_annual_est",
    "perf_fee_flow", "perf_fee_pct_annual_est", "fiscal_reset_suspect",
    "disclosed_taxa_adm", "disclosed_taxa_adm_min", "disclosed_taxa_adm_max",
    "disclosed_taxa_perfm", "disclosed_taxa_adm_info", "disclosed_taxa_perfm_info",
    "disclosed_source", "disclosed_as_of", "disclosed_age_months", "disclosed_n_classes",
    "disclosed_note", "estimate_label",
]


def _fee_columns() -> list:
    fn = _function("portfolio_fees")
    out = _strip(fn[fn.index("RETURNS TABLE ("): fn.index("LANGUAGE plpgsql")])
    return re.findall(r"^\s*(\w+)\s+(?:TEXT|NUMERIC|DATE|INT|BOOLEAN)\b", out, re.M)


def test_v52_appends_to_the_v51_columns_without_touching_them():
    cols = _fee_columns()
    assert cols[: len(V51_COLUMNS)] == V51_COLUMNS
    appended = cols[len(V51_COLUMNS):]
    for name in (
        "disclosed_origin", "disclosed_age_days", "filed_zero", "implausible_filed",
        "taxa_adm_filed_raw", "extrato_taxa_perfm", "extrato_param_taxa_perfm",
        "extrato_calc_taxa_perfm", "extrato_inf_taxa_perfm", "extrato_taxa_ingresso_pr",
        "extrato_taxa_saida_pr", "extrato_class_note", "lamina_pr_pl_despesa",
        "lamina_dt_ini_despesa", "lamina_dt_fim_despesa",
    ):
        assert name in appended, name
    assert len(cols) == len(set(cols)), "a duplicated output column"


def test_v52_changes_the_return_type_so_the_function_is_dropped_first():
    body = _strip(SQL31)
    drop = body.index("DROP FUNCTION IF EXISTS api.portfolio_fees(TEXT[], DATE);")
    assert drop < body.index("CREATE OR REPLACE FUNCTION api.portfolio_fees(")
    assert "GRANT EXECUTE ON FUNCTION api.portfolio_fees(TEXT[], DATE) TO anon, authenticated" in body


def test_the_extrato_is_read_first_then_the_lamina_then_cad_fi():
    body = _strip(_function("portfolio_fees"))
    assert "to_regclass('public.vw_fi_extrato_latest')" in body
    assert "FROM public.vw_fi_extrato_latest" in body
    order = body.index("WHEN a.use_ext THEN 'extrato'")
    assert order < body.index("WHEN a.use_lam THEN 'lamina'") < body.index("THEN 'cad_fi'")
    # An Extrato row without a parseable fee does not hide the lamina; a 0 or a value
    # above 5 does not fall through to an OLDER source (it is read, not skipped). v55
    # (#552): it gives way only to a NEWER lamina with a single fee in (0, 5].
    assert "(x.cnpj IS NOT NULL AND x.x_adm IS NOT NULL AND NOT n.lam_newer) AS use_ext" in body


def test_the_owners_reading_rules_are_applied_when_reading_not_when_storing():
    body = _strip(_function("portfolio_fees"))
    assert "COALESCE(e.fee_raw = 0, FALSE) AS is_zero" in body
    assert "COALESCE(e.fee_raw > 5 OR e.fee_raw < 0, FALSE) AS is_implausible" in body
    assert "CASE WHEN f.is_implausible THEN NULL ELSE f.fee_raw END" in body
    # The ingest stores TAXA_ADM as filed: no clip or zero-fix in the field map or the ingest.
    ingest = (ROOT / "src" / "pipeline" / "ingest_fi.py").read_text(encoding="utf-8")
    block = ingest[ingest.index("def ingest_fi_extrato("): ingest.index("def ingest_fi_balancete(")]
    assert "> 5" not in block and "min(" not in block and "max(" not in block


def test_catalog_v52_says_extrato_first_and_names_the_flags():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 52
    text = str(catalog_payload()["constraints"]) if "constraints" in catalog_payload() else ""
    text += str(catalog_payload())
    for needle in ("disclosed_origin", "filed_zero", "implausible_filed", "taxa_adm_filed_raw",
                   "lamina_pr_pl_despesa"):
        assert needle in text, needle
    assert f'"version": {CATALOG_VERSION}' in SQL19


# --- catalog v55: the lamina beside the Extrato, or the newer lamina (issue #552) ------

V52_LAST = "lamina_expense_note"
V55_COLUMNS = [
    "fee_resolution", "lamina_taxa_adm", "lamina_taxa_adm_min", "lamina_taxa_adm_max",
    "lamina_n_classes", "lamina_age_months", "extrato_taxa_adm_filed", "extrato_as_of",
    "extrato_lamina_ratio", "extrato_scale_factor",
]


def test_v55_appends_after_the_v52_columns_without_touching_them():
    cols = _fee_columns()
    assert cols[: len(V51_COLUMNS)] == V51_COLUMNS
    last = cols.index(V52_LAST)
    assert last == 45, "the 46 columns of v52 keep their order"
    assert cols[last + 1: last + 1 + len(V55_COLUMNS)] == V55_COLUMNS


def test_v55_lamina_newer_needs_a_newer_plausible_lamina_and_never_rescales():
    body = _strip(_function("portfolio_fees"))
    rule = body[body.index("AS lam_newer") - 400: body.index("AS lam_newer")]
    for needle in ("(x.x_adm = 0 OR x.x_adm > 5)", "s.lam_single > 0 AND s.lam_single <= 5",
                   "l.dt_comptc > x.x_dt"):
        assert needle in rule, needle
    # The scale flag is a factor of exactly 10 or 100 within two-decimal rounding: a flag column, never a fee.
    assert "abs(f.x_adm - 10 * f.lam_single) <= 10 * 0.005 + 0.005 THEN 10" in body
    assert "abs(f.x_adm - 100 * f.lam_single) <= 100 * 0.005 + 0.005 THEN 100" in body
    assert "x_adm / 100" not in body and "x_adm / 10" not in body  # no filed value is divided by a factor


def test_catalog_v55_names_the_resolution_and_the_flag():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 55
    text = str(catalog_payload())
    for needle in ("fee_resolution", "lamina_newer", "extrato_lamina_beside", "extrato_scale_factor",
                   "lamina_taxa_adm", "extrato_taxa_adm_filed"):
        assert needle in text, needle


# --- catalog v56: ETFs carry a fee; a newer lamina's fee is summed (owner, 2026-10-03) ------

V56_COLUMNS = ["etf_ticker", "etf_site_taxa_adm", "etf_site_as_of", "etf_site_source", "etf_site_note"]


def test_v56_appends_the_etf_columns_after_the_v55_ones():
    cols = _fee_columns()
    last = cols.index(V55_COLUMNS[-1])
    assert cols[: last + 1][-len(V55_COLUMNS):] == V55_COLUMNS
    assert cols[last + 1:last + 1 + len(V56_COLUMNS)] == V56_COLUMNS
    assert len(cols) == len(set(cols))


def test_v56_the_etf_site_fee_is_never_a_disclosed_fee():
    body = _strip(_function("portfolio_fees"))
    # read dynamically, joined by the registry's ticker, the newest snapshot with a fee
    assert "to_regclass('public.etf_market_snapshot')" in body
    assert "JOIN public.cvm_etf_registry r ON r.ticker = x.ticker" in body
    assert "x.taxa_adm_pct IS NOT NULL" in body and "ORDER BY x.ticker, x.snapshot_date DESC" in body
    # the disclosed_* origin list is unchanged: the site is not one of them
    origin = body[body.index("WHEN a.use_ext THEN 'extrato'"): body.index("END AS origin")]
    assert "etf" not in origin
    fn = _function("portfolio_fees")
    assert "a third-party site, not a CVM filing" in fn and "never in disclosed_*" in fn


def test_v56_resolver_matches_an_etf_ticker_exactly_and_never_ambiguously():
    fn = _strip(_function("portfolio_resolve"))
    assert "'etf_ticker'" in fn
    assert "JOIN public.cvm_etf_registry e ON e.ticker = upper(btrim(l.input_name))" in fn
    assert "WHEN r1.kind IN ('cnpj', 'etf_ticker') OR r1.n_cand = 1 THEN FALSE" in fn
    # exact and trigram skip a line the ETF registry matched
    assert fn.count("NOT EXISTS (SELECT 1 FROM by_etf b WHERE b.line_no = l.line_no)") == 2


def test_catalog_v56_names_the_etf_columns_and_the_lamina_newer_sum():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 56
    text = str(catalog_payload())
    for needle in ("etf_ticker", "etf_site_taxa_adm", "etf_site_note", "match_kind etf_ticker",
                   "For lamina_newer the newer lamina's fee in disclosed_taxa_adm is a disclosed fee like any other"):
        assert needle in text, needle
    assert f'"version": {CATALOG_VERSION}' in SQL19


# --- catalog v57: an ETF's cotistas and PL from the fee's snapshot (owner, 2026-10-03) -------

V57_COLUMNS = ["etf_site_nr_cotistas", "etf_site_pl"]


def test_v57_appends_cotistas_and_pl_last():
    cols = _fee_columns()
    last = cols.index(V56_COLUMNS[-1])
    assert cols[last + 1:] == V57_COLUMNS
    assert len(cols) == len(set(cols))


def test_v57_cotistas_and_pl_come_from_the_fee_row_and_are_never_summed():
    body = _strip(_function("portfolio_fees"))
    # the same DISTINCT ON row as the fee: one date (etf_site_as_of) for the three values
    assert "x.cotistas, x.nav" in body and "x.taxa_adm_pct IS NOT NULL" in body
    assert "(e ->> 'cotistas')::int AS s_cotistas" in body and "(e ->> 'nav')::numeric AS s_pl" in body
    assert "es.s_cotistas" in body and "es.s_pl" in body
    # served as stored: never multiplied or divided on the way out, never in the balancete NAV or a fee flow
    for bad in ("s_pl *", "s_pl /", "s_cotistas *"):
        assert bad not in body, bad
    fn = _function("portfolio_fees")
    assert "descriptive facts, never summed" in fn


def test_catalog_v57_names_cotistas_and_pl():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    assert CATALOG_VERSION >= 57
    text = str(catalog_payload())
    for needle in ("etf_site_nr_cotistas", "etf_site_pl", "SAME snapshot (etf_site_as_of)"):
        assert needle in text, needle
    assert f'"version": {CATALOG_VERSION}' in SQL19
