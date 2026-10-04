"""api.portfolio_movement (31_api_portfolio.sql, catalog v54): movimento incomum of a held fund.

Offline: the SQL text, the catalog, the MCP tool and the CI wiring are pinned to each other. The behaviour is executed in
tests/sql/portfolio_behaviour.sql (CI's sql-compile job, on synthetic funds): winsorization at the class's own 1st and
99th percentile, the minimum of 30 peers, the strict thresholds, every nao_avaliado reason. What this file keeps true
(owner decisions of 2026-10-03, map #510):

* the movement is the monthly QUOTA return from fact_fund_monthly, not a NAV change, and the class is the Extrato's
  classe_anbima as filed, not read from a fund name;
* the class mean and sd are taken on values winsorized at the 1st and 99th percentile, and the fund's own value is not;
* atencao beyond 2 and forte beyond 3, strictly, decided in one place; investigator_trigger is exactly `forte`;
* a fund that cannot be judged is nao_avaliado with a Portuguese reason, never skipped and never a zero;
* the house serving rules: SECURITY DEFINER with an empty pinned search_path, one page plus one row, assert_row_cap,
  at most 200 CNPJs, REVOKE from PUBLIC and GRANT to anon / authenticated / silo_api.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL31 = (ANALYTICAL / "31_api_portfolio.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
BEHAVIOUR = (ROOT / "tests" / "sql" / "portfolio_behaviour.sql").read_text(encoding="utf-8")
SIG = "api.portfolio_movement(TEXT[], DATE)"


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL31.index("CREATE OR REPLACE FUNCTION api.portfolio_movement(")
    return SQL31[start: SQL31.index("$fn$;", SQL31.index("AS $fn$", start)) + 5]


def _body() -> str:
    return _strip(_function())


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_definer_empty_search_path_and_grants():
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head and "STABLE" in head
    flat = _flat(SQL31)
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in flat
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in flat
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in flat
    # every relation is schema-qualified: the empty search_path would not find a bare one
    body = re.sub(r"'[^']*'", "''", _body())
    for rel in ("fact_fund_monthly", "cvm_fund_registry", "cvm_etf_registry", "vw_fi_extrato_latest", "mv_period_completeness"):
        for m in re.finditer(rf"(?<![\w.]){rel}\b", body):
            raise AssertionError(f"unqualified relation {rel} at offset {m.start()}")


def test_the_threshold_helper_is_internal_and_the_only_place_the_levels_are_decided():
    flat = _flat(SQL31)
    assert "REVOKE ALL ON FUNCTION public.portfolio_movement_level(NUMERIC) FROM PUBLIC;" in flat
    assert "GRANT EXECUTE ON FUNCTION public.portfolio_movement_level" not in flat
    helper = _flat(_strip(SQL31[SQL31.index("CREATE OR REPLACE FUNCTION public.portfolio_movement_level("):]))
    helper = helper[: helper.index("$fn$;", helper.index("AS $fn$"))]
    # strictly greater, on the absolute value; 3 before 2
    assert "WHEN abs(p_z) > 3 THEN 'forte'" in helper and "WHEN abs(p_z) > 2 THEN 'atencao'" in helper
    assert helper.index("> 3") < helper.index("> 2")
    assert ">=" not in helper
    body = _body()
    assert "public.portfolio_movement_level(d.zz)" in body
    assert "abs(" not in body and ">= 2" not in body and ">= 3" not in body  # no second copy of the rule
    assert "investigator_trigger" in body and "= 'forte'" in body


def test_movement_is_the_monthly_quota_return_not_a_nav_change():
    body = _body()
    assert "fact_fund_monthly" in body and "vl_quota" in body
    assert "(c.vl_quota / p.vl_quota - 1) * 100" in body and "(o.q1 / o.q0 - 1) * 100" in body
    assert "vl_patrim_liq" not in body and "cvm_fi_diario" not in body
    # the previous month is the calendar month before, the same stable quota subclass, a positive quota
    assert "v_prev := (v_cur - INTERVAL '1 month')::date" in body
    assert "quota_subclass_id IS NOT DISTINCT FROM" in body
    assert "c.vl_quota > 0" in body and "p.vl_quota > 0" in body
    assert "c.entity_type = 'fi'" in body and "p.entity_type = 'fi'" in body


def test_class_is_the_extrato_label_as_filed_and_never_read_from_a_name():
    body = _body()
    assert "vw_fi_extrato_latest" in body and "classe_anbima" in body
    assert "fund_name" in body  # served, but never compared, split or matched
    assert not re.search(r"(like|ilike|similarity|~)\s*[^;]*fund_name", body, re.I)
    assert "split_part(d.cls, ' - ', 1)" in body  # display split of the filed label only
    # the peer group is the whole label; there is no fallback to a wider class
    assert "ON b.cls = q.cls" in body and "LEFT JOIN stats s ON s.cls = x.cls" in body
    assert "COALESCE(d.n, 0) < v_min" in body


def test_mean_and_sd_are_winsorized_at_the_class_1st_and_99th_percentile_and_the_own_value_is_not():
    body = _body()
    assert "percentile_cont(0.01) WITHIN GROUP (ORDER BY q.ret)" in body
    assert "percentile_cont(0.99) WITHIN GROUP (ORDER BY q.ret)" in body
    assert "avg(least(greatest(q.ret, b.p01), b.p99))" in body
    assert "stddev_samp(least(greatest(q.ret, b.p01), b.p99))" in body
    assert "GROUP BY q.cls" in body  # per class (and the month is one)
    # z uses the fund's raw return, own_ret, against the winsorized mean and sd
    assert "(j.own_ret - j.mean) / j.sd" in body
    assert "own_ret" in body and "least(greatest(j.own_ret" not in body


def test_the_minimum_of_30_peers_and_the_complete_month_rule():
    body = _body()
    assert "v_min      INT  := 30" in body
    assert "j.n >= v_min" in body and "d.n >= v_min" in body
    assert "j.sd > 0" in body
    assert "mv_period_completeness" in body and "pc.entity_type = 'fi'" in body
    assert "public.latest_complete_period('fi')" in body
    assert "WHERE v_complete" in body  # no peers are read for an incomplete month


def test_every_fund_that_cannot_be_judged_is_returned_with_a_portuguese_reason():
    body = _body()
    for fragment in (
        "incompleto", "ETF: fora do universo mensal", "não é fundo FI com cota diária", "CNPJ não encontrado no cadastro",
        "sem informe diário do fundo em", "ausente ou não positiva", "sem cota no mês anterior", "a subclasse que fornece a cota mudou",
        "fundo fora do Extrato da CVM", "classe ANBIMA não informada no Extrato", "mínimo", "desvio padrão da classe",
    ):
        assert fragment in body, f"missing reason: {fragment}"
    assert "COALESCE(public.portfolio_movement_level(d.zz), 'nao_avaliado') AS level" in body
    # one row per distinct CNPJ asked for: the request is the driving table, nothing is dropped
    assert "FROM ids i" in body and "LEFT JOIN" in body
    # the family test is on whole entity names ('fidc' contains 'fi')
    assert "'fi' = ANY (string_to_array(d.types, ','))" in body


def test_row_cap_and_the_200_cnpj_refusal():
    body = _body()
    assert "LIMIT 1001" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page), FALSE, 'portfolio_movement')" in body
    assert "v_n > 200" in body and "To fix" in body and "ERRCODE = '22023'" in body
    assert "CASE WHEN p_fn IN ('portfolio_fees', 'portfolio_lookthrough', 'portfolio_movement')" not in SQL19  # sanity: shape below
    assert "WHEN p_fn IN ('portfolio_fees', 'portfolio_lookthrough', 'portfolio_movement') THEN" in SQL19


def test_columns_are_the_documented_ones_in_order():
    fn = _function()
    head = fn[fn.index("RETURNS TABLE"): fn.index("LANGUAGE plpgsql")]
    cols = re.findall(r"^\s{4}(\w+)\s+(?:TEXT|DATE|INT|NUMERIC|BOOLEAN)\b", head, re.M)
    assert cols == [
        "cnpj", "fund_name", "month", "class", "subclass", "class_as_filed", "class_as_of", "n_peers", "own_value_pct",
        "class_mean_pct", "class_sd_pct", "class_p01_pct", "class_p99_pct", "z", "level", "investigator_trigger",
        "min_peers", "reason",
    ]


def test_catalog_openapi_and_mcp_carry_the_function():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    c = catalog_payload()
    assert CATALOG_VERSION >= 54
    assert "portfolio_movement" in c["limits"]["page"]["all"]
    assert "portfolio_movement" in c["limits"]["page"]["functions"]["raise_only"]
    assert c["postgrest"]["portfolio_movement"] == "POST /rest/v1/rpc/portfolio_movement"
    text = " ".join(c["constraints"])
    for phrase in ("api.portfolio_movement", "winsorized at the class's own 1st and 99th percentile", "forte when |z| > 3",
                   "exactly 2 is normal", "nao_avaliado", "min_peers (30)", "not a forecast, a verdict or a recommendation"):
        assert phrase in text, phrase
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert "/rpc/portfolio_movement" in spec["paths"]
    tools = (ROOT / "supabase" / "functions" / "silo-mcp" / "tools.ts").read_text(encoding="utf-8")
    assert 't("portfolio_movement",' in tools


def test_the_behaviour_test_executes_the_owners_cases():
    for needle in (
        "portfolio_movement OK",
        "winsorization did not matter in the fixture",
        "public.portfolio_movement_level(2) <> 'normal'",
        "public.portfolio_movement_level(3) <> 'atencao'",
        "apenas 10 fundos da classe TESTE - POUCOS%mínimo 30%",
        "desvio padrão da classe TESTE - ZERO é zero",
        "fundo fora do Extrato%",
        "classe ANBIMA não informada%",
        "an incomplete month must not be judged",
    ):
        assert needle in BEHAVIOUR, needle
    assert BEHAVIOUR.index("portfolio_movement OK") < BEHAVIOUR.index("portfolio grants OK")
