"""api.risk_decompose (44_api_risk_decompose.sql, catalog v90).

Offline: the SQL text, the catalog, the v2 registry and the dashboard source
are pinned to each other. The executed behaviour (the split adds to 1, the
beta is the OLS slope on joined levels, the price-only fallback, the shock
rerun, the window clamp, the refusals, the dashboard view) is in
tests/sql/risk_decompose_behaviour.sql, which CI's sql-compile job runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from serve.catalog import CATALOG_VERSION, catalog_payload
from serve.endpoint_manifest import manifest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL44 = (ANALYTICAL / "44_api_risk_decompose.sql").read_text(encoding="utf-8")
SIG = "api.risk_decompose(TEXT, DATE, DATE, TEXT)"
INTERNAL = (
    "api.risk_sector_leg(TEXT)",
    "api.risk_split(DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION[], DOUBLE PRECISION)",
)


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _function() -> str:
    start = SQL44.index("CREATE OR REPLACE FUNCTION api.risk_decompose(")
    return SQL44[start: SQL44.index("$fn$;", start)]


def test_file_is_one_guarded_transaction_after_19_and_28():
    body = _strip(SQL44)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.quote_history(text, date, date, text, text, text[])') IS NULL" in body
    assert "to_regclass('public.mv_research_universe') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("44_api_risk_decompose.sql") > ordered.index("28_api_research.sql")


def test_function_is_granted_and_the_helpers_are_not():
    body = _strip(SQL44)
    head = _function()
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert f"REVOKE ALL ON FUNCTION {SIG} FROM PUBLIC;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO anon, authenticated;" in body
    assert f"GRANT EXECUTE ON FUNCTION {SIG} TO silo_api;" in body
    for helper in INTERNAL:
        assert f"REVOKE ALL ON FUNCTION {helper} FROM PUBLIC;" in body
        name = helper.split("(")[0]
        assert not re.search(rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+{re.escape(name)}\(", body)
    assert "REVOKE ALL ON public.mv_risk_decompose_ibov FROM PUBLIC, anon, authenticated;" in body
    assert not re.search(r"GRANT\s+\w+\s+ON\s+(TABLE\s+)?public\.", body)


def test_one_row_so_not_capped_and_the_manifest_agrees():
    endpoint = manifest()["risk_decompose"]
    assert endpoint.granted and endpoint.kind == "rpc"
    assert not endpoint.refuses and not endpoint.pages
    assert endpoint.params[:4] == ("p_ticker", "p_from", "p_to", "p_sector") or list(endpoint.params[:4]) == [
        "p_ticker", "p_from", "p_to", "p_sector"]
    for helper in ("risk_sector_leg", "risk_split"):
        assert not manifest()[helper].granted


def test_returns_join_levels_before_returns():
    body = _strip(_function())
    # The levels are joined first (lv), and the returns come from the joined rows (ret).
    assert body.index("lv AS (") < body.index("ret AS (")
    assert "lv.lvl / lag(lv.lvl) OVER w - 1" in body
    assert "lv.im / lag(lv.im) OVER w - 1" in body


def test_only_the_contract_refusal_is_caught_for_the_dashboard():
    body = _strip(SQL44)
    handlers = re.findall(r"EXCEPTION\s+WHEN\s+([^\n]+?)\s+THEN", body)
    assert handlers == ["SQLSTATE '22023'"], handlers


def test_catalog_publishes_it():
    payload = catalog_payload()
    assert CATALOG_VERSION >= 90
    assert payload["postgrest"]["risk_decompose"] == "POST /rest/v1/rpc/risk_decompose"
    assert "risk_decompose" not in payload["limits"]["page"]["all"]
    assert any("api.risk_decompose" in c for c in payload["constraints"])


def test_v2_kind_maps_to_the_sql_arguments():
    text = (ROOT / "supabase/functions/silo-api/registry.ts").read_text(encoding="utf-8")
    raw = text.split("// BEGIN REGISTRY", 1)[1].split("= ", 1)[1]
    raw = raw.split("// END REGISTRY", 1)[0].rstrip().rstrip(";")
    prices = next(r for r in json.loads(raw)["resources"] if r["name"] == "prices")
    plan = prices["kinds"]["risk"]
    assert plan["endpoint"] == "risk_decompose"
    assert plan["args"] == {"id": "p_ticker", "from": "p_from", "to": "p_to", "sector": "p_sector"}
    assert plan["paging"]["method"] == "single_page"
    sector = next(p for p in prices["parameters"] if p["name"] == "sector")
    assert sector["visibility"] == "hidden" and sector["default"] is None


def test_dashboard_source_reads_the_view_with_a_zero_row_guard():
    src = (ROOT / "dashboard/sources/supabase/risk_decompose_ibov.sql").read_text(encoding="utf-8")
    assert "from mv_risk_decompose_ibov" in src
    assert "where not exists (select 1 from r)" in src
    preflight = (ROOT / "dashboard/scripts/preflight.js").read_text(encoding="utf-8")
    assert "relation: 'mv_risk_decompose_ibov'" in preflight
