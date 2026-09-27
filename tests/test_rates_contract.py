"""The Brazilian rate curve in schema `api` (27_api_rates.sql, catalog v42).

Offline: the SQL text, the parser's curve list, the catalog and the SDK are
pinned to each other. What this file keeps true:

* the house serving rules from 19 / 26: SECURITY DEFINER with an empty pinned
  search_path, REVOKE from PUBLIC then GRANT to anon / authenticated /
  silo_api, one page plus one row and api.assert_row_cap refusing above it,
  22023 on bad input;
* nothing is derived except contract_month, read with B3's month letters, and
  curve_history serves B3's own FIXED vertices only, never an interpolation;
* the curve registry is the parser's DEFAULT_CURVES, with each curve's rate
  convention (DOC is linear 360, the other two compound on 252);
* every comment that serves a curve says its long end is B3's extrapolation;
* coverage() reports both tables, each with its own landed_at source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL27 = (ANALYTICAL / "27_api_rates.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")
SQL11 = (ANALYTICAL / "11_indexes.sql").read_text(encoding="utf-8")

SERVED = ("future_curve", "future_series", "curve", "curve_history")
SIGNATURES = {
    "future_curve": "TEXT, DATE",
    "future_series": "TEXT, DATE, DATE",
    "curve": "TEXT, DATE",
    "curve_history": "TEXT, INT, DATE, DATE",
}


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _chunk(name: str) -> str:
    start = SQL27.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL27.index("$fn$;", start) + len("$fn$;")
    return SQL27[start:end]


def _signature(name: str) -> str:
    chunk = _chunk(name)
    return chunk[chunk.index("(") + 1: chunk.index("\nRETURNS")]


def _body(name: str) -> str:
    """The query part only: string literals blanked, so messages never match."""
    b = _strip(_chunk(name))
    return re.sub(r"'[^']*'", "''", b[b.index("BEGIN"):])


def _comment(name: str) -> str:
    start = SQL27.index(f"COMMENT ON FUNCTION api.{name}(")
    return SQL27[start: SQL27.index("';\n", start)]


def _coverage() -> str:
    start = SQL19.index("CREATE OR REPLACE FUNCTION api.coverage()")
    return SQL19[start: SQL19.index("COMMENT ON FUNCTION api.coverage()", start)]


# ---------------------------------------------------------------------------
# Wiring and privileges
# ---------------------------------------------------------------------------


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL27)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regclass('public.b3_futures_settlement') IS NULL" in body
    assert "to_regclass('public.b3_reference_rate') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("27_api_rates.sql") > ordered.index("19_api_contract.sql")


def test_exactly_the_served_functions_and_the_internal_registry_are_created():
    created = set(re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL27)))
    assert created == set(SERVED) | {"curve_registry"}


@pytest.mark.parametrize("name", SERVED)
def test_definer_empty_search_path_and_grants(name):
    head = _chunk(name)
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    sig = f"api.{name}({SIGNATURES[name]})"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in SQL27
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in SQL27
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in SQL27


def test_the_registry_is_internal():
    body = _strip(SQL27)
    assert "REVOKE ALL ON FUNCTION api.curve_registry() FROM PUBLIC;" in body
    assert not re.search(r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+api\.curve_registry", body)


@pytest.mark.parametrize("name", SERVED)
def test_every_relation_is_schema_qualified(name):
    body = _body(name)
    for rel in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", body, re.I):
        if rel.lower() == "page":
            continue
        assert rel.startswith(("public.", "api.")), f"{name}: unqualified {rel}"


@pytest.mark.parametrize("name", SERVED)
def test_refuses_above_one_page_instead_of_trimming(name):
    body = _strip(_chunk(name))
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body
    assert "p_after" not in body
    assert "ERRCODE = '22023'" in body


@pytest.mark.parametrize("name", SERVED)
def test_nothing_is_derived(name):
    body = _body(name).lower()
    for fn in ("avg(", "sum(", "exp(", "ln(", "power(", "stddev", "lag(", "lead(", "interpolat"):
        assert fn not in body, f"{name} derives something ({fn})"


# ---------------------------------------------------------------------------
# DI1 futures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ("future_curve", "future_series"))
def test_contract_month_is_read_with_b3s_month_letters(name):
    body = _strip(_chunk(name))
    assert "strpos('FGHJKMNQUVXZ', substr(f.ticker, 4, 1))" in body
    assert "make_date(2000 + substr(f.ticker, 5, 2)::int" in body
    assert "FROM public.b3_futures_settlement f" in body


def test_month_letters_are_the_ones_the_ingest_keeps():
    from src.parsers import b3_price_report as pr

    # Twelve letters, January first (the DI1 contract specification), and
    # the same string the ingest's outright-ticker filter uses.
    assert pr._MONTH_LETTERS == "FGHJKMNQUVXZ"
    for name in ("future_curve", "future_series"):
        assert f"'{pr._MONTH_LETTERS}'" in _strip(_chunk(name))


def test_future_series_refuses_anything_but_an_outright_di1_code():
    body = _strip(_chunk("future_series"))
    assert "v_ticker !~ '^DI1[FGHJKMNQUVXZ][0-9]{2}$'" in body
    assert "f.ticker = v_ticker" in body


def test_future_curve_serves_di1_only_and_says_the_quotes_are_rates():
    body = _strip(_chunk("future_curve"))
    assert "IF v_root <> 'DI1' THEN" in body
    comment = _comment("future_curve")
    assert "RATES" in comment and "PU" in comment
    assert "2018-01-02" in comment


# ---------------------------------------------------------------------------
# Reference curves
# ---------------------------------------------------------------------------


def _registry() -> dict[str, str]:
    chunk = SQL27[SQL27.index("CREATE OR REPLACE FUNCTION api.curve_registry()"):]
    chunk = chunk[: chunk.index("$$;")]
    return dict(re.findall(r"\('(\w+)',\s*'[^']*',\s*'(\w+)'", chunk))


def test_registry_is_the_parsers_curve_list_with_each_convention():
    from src.parsers.b3_taxa_swap import DEFAULT_CURVES

    reg = _registry()
    assert set(reg) == set(DEFAULT_CURVES)
    assert reg == {"PRE": "exp_252", "DOC": "linear_360", "DPL": "exp_252"}


@pytest.mark.parametrize("name", ("curve", "curve_history"))
def test_unknown_curves_list_the_registry_and_rate_basis_rides_on_every_row(name):
    body = _strip(_chunk(name))
    assert "FROM api.curve_registry() reg WHERE reg.curve = v_curve" in body
    assert f"'unknown reference curve %; {name} serves: %'" in body
    cols = body[body.index("RETURNS TABLE ("): body.index("\n)\nLANGUAGE")]
    assert re.search(r"^\s*rate_basis\s+TEXT", cols, re.M)


def test_curve_history_serves_fixed_vertices_only():
    body = _strip(_chunk("curve_history"))
    assert "v_code := lpad(p_tenor_days::text, 5, '0');" in body
    page = body[body.index("WITH page AS"):]
    assert "r.vertex_type = 'F'" in page and "r.vertex_code = v_code" in page
    # An unknown tenor is refused with the fixed tenors of the newest session.
    assert "is not one of B3''s fixed % vertices" in body
    # Its access path has its own partial index.
    assert "ON b3_reference_rate (curve, vertex_code, trade_date)" in SQL11
    assert "WHERE vertex_type = 'F';" in SQL11[SQL11.index("idx_b3_reference_rate_fixed"):]


@pytest.mark.parametrize("name", ("curve", "curve_history"))
def test_the_extrapolated_long_end_is_stated(name):
    comment = _comment(name)
    assert "EXTRAPOLAT" in comment.upper()
    assert "Manual de Curvas v21" in comment


def test_curve_comment_states_each_convention():
    comment = _comment("curve")
    assert "LINEAR on 360 calendar days" in comment
    assert "(1 + PRE) / (1 + DPL)" in comment


# ---------------------------------------------------------------------------
# coverage(), catalog, SDK
# ---------------------------------------------------------------------------


def test_coverage_reports_both_tables_with_their_own_landed_source():
    cov = _coverage()
    for dataset, entity, table in (("di_futures", "*market_price_report*", "b3_futures_settlement"),
                                   ("reference_curves", "*market_reference_rate*", "b3_reference_rate")):
        seg = cov[cov.index(f"SELECT '{dataset}'::text"):]
        seg = seg[: seg.index("UNION ALL") if "UNION ALL" in seg else seg.index("\n    )")]
        assert f"'{entity}'::text" in seg, dataset
        assert f"FROM public.{table}" in seg, dataset
        # One backward index probe per date, never an aggregate over a scan.
        assert "FILTER (WHERE" not in seg
    assert "l.entity = 'market' AND l.doc_type = 'b3_price_report'" in cov
    assert "l.entity = 'market' AND l.doc_type = 'b3_reference_rate'" in cov


def test_catalog_publishes_the_four():
    from serve.catalog import CATALOG_VERSION, CONSTRAINTS, catalog_payload

    assert CATALOG_VERSION >= 42
    payload = catalog_payload()
    for name in SERVED:
        assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"
        assert name in payload["limits"]["page"]["all"]
        assert name in payload["limits"]["page"]["functions"]["raise_only"]
    (c,) = [c for c in CONSTRAINTS if c.startswith("DI FUTURES AND B3'S REFERENCE CURVES")]
    assert "EXTRAPOLATION" in c and "LINEAR on 360" in c and "QUOTED IN RATE" in c


def test_sdk_sends_exactly_the_declared_parameters():
    from sdk.silo_client.client import KNOWN_CATALOG_VERSION, SiloClient
    from serve.catalog import CATALOG_VERSION

    assert KNOWN_CATALOG_VERSION == CATALOG_VERSION
    sent = {}

    class Stub(SiloClient):
        def __init__(self):
            pass

        def _rpc(self, fn, body, page=False):
            sent[fn] = body
            return []

    c = Stub()
    c.future_curve(trade_date="2026-09-25")
    c.future_series("DI1F27", start="2026-01-01")
    c.curve("DOC")
    c.curve_history("PRE", 360, end="2026-09-01")
    for name in SERVED:
        declared = set(re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M))
        assert set(sent[name]) == declared, name
    assert sent["future_curve"]["p_root"] == "DI1"
    assert sent["future_series"]["p_ticker"] == "DI1F27"
    assert sent["curve"]["p_curve"] == "DOC"
    assert sent["curve_history"]["p_tenor_days"] == 360
    assert sent["curve_history"]["p_to"] == "2026-09-01"
