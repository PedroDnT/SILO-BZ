"""The portfolio-diagnosis reads in schema `api` (31_api_portfolio.sql, catalog v51).

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


def test_exactly_the_three_api_functions_are_created():
    created = re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL31))
    assert created == ["portfolio_resolve", "portfolio_fees", "portfolio_lookthrough"]


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
    assert "('portfolio_fees', 'portfolio_lookthrough')" in helper
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
