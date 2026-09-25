"""Company events, macro series and PTAX in schema `api` (26_api_events_macro.sql, v36).

Offline: the SQL text, the pipeline's series registry, the catalog and the SDK
are pinned to each other. What this file keeps true:

* the house serving rules from 19 / 24 — SECURITY DEFINER with an empty pinned
  search_path, REVOKE from PUBLIC then GRANT to anon / authenticated / silo_api,
  one page plus one row and api.assert_row_cap refusing above it, 22023 on bad
  input;
* company_events resolves p_id through api.company_ref (the resolver
  api.financials uses) and never by a name, serves one row per protocol at its
  newest version, and carries CVM's RAD link as source_url;
* macro_series serves exactly SGS_SERIES minus INFLATION_SERIES, refuses the
  IPCA codes with a pointer to api.inflation and lists what exists otherwise;
* ptax lists the currencies bacen_ptax actually holds when refusing;
* nothing is derived — no chain, average, annualisation or fill;
* coverage() reports all three, each with its own landed_at source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL26 = (ANALYTICAL / "26_api_events_macro.sql").read_text(encoding="utf-8")
SQL19 = (ANALYTICAL / "19_api_contract.sql").read_text(encoding="utf-8")

SERVED = ("company_events", "macro_series", "ptax")
SIGNATURES = {
    "company_events": "TEXT, DATE, DATE, TEXT",
    "macro_series": "TEXT, DATE, DATE",
    "ptax": "TEXT, DATE, DATE",
}


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _chunk(name: str) -> str:
    start = SQL26.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL26.index("$fn$;", start) + len("$fn$;")
    return SQL26[start:end]


def _signature(name: str) -> str:
    chunk = _chunk(name)
    return chunk[chunk.index("(") + 1: chunk.index("\nRETURNS")]


def _body(name: str) -> str:
    """The query part only: string literals blanked, so messages never match."""
    b = _strip(_chunk(name))
    return re.sub(r"'[^']*'", "''", b[b.index("BEGIN"):])


def _coverage() -> str:
    start = SQL19.index("CREATE OR REPLACE FUNCTION api.coverage()")
    return SQL19[start: SQL19.index("COMMENT ON FUNCTION api.coverage()", start)]


# ---------------------------------------------------------------------------
# Wiring and privileges
# ---------------------------------------------------------------------------


def test_file_is_one_guarded_transaction_after_19():
    body = _strip(SQL26)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regprocedure('api.company_ref(text)') IS NULL" in body
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    assert ordered.index("26_api_events_macro.sql") > ordered.index("19_api_contract.sql")


def test_exactly_the_served_functions_and_the_internal_registry_are_created():
    created = set(re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL26)))
    assert created == set(SERVED) | {"macro_registry"}


@pytest.mark.parametrize("name", SERVED)
def test_definer_empty_search_path_and_grants(name):
    head = _chunk(name)
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    sig = f"api.{name}({SIGNATURES[name]})"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in SQL26
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in SQL26
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO silo_api;" in SQL26


def test_the_registry_is_internal():
    body = _strip(SQL26)
    assert "REVOKE ALL ON FUNCTION api.macro_registry() FROM PUBLIC;" in body
    assert not re.search(r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+api\.macro_registry", body)


@pytest.mark.parametrize("name", SERVED)
def test_every_relation_is_schema_qualified(name):
    body = _body(name)
    for rel in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", body, re.I):
        if rel.lower() in {"ref", "latest", "page"}:
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
    for fn in ("avg(", "sum(", "exp(", "ln(", "stddev", "lag(", "lead(", "coalesce(g.v", "interpolat"):
        assert fn not in body, f"{name} derives something ({fn})"


# ---------------------------------------------------------------------------
# company_events
# ---------------------------------------------------------------------------


def test_company_is_resolved_like_financials_and_never_by_name():
    body = _body("company_events")
    assert "FROM api.company_ref(p_id) r" in body
    assert "JOIN ref r ON r.cd_cvm = e.cd_cvm" in body
    assert not re.search(r"ilike|denom_cia|nome_companhia|similarity|%", body, re.I)


def test_one_row_per_protocol_at_its_newest_version():
    body = _body("company_events")
    assert "SELECT DISTINCT ON (e.protocolo)" in body
    assert "ORDER BY e.protocolo, e.versao DESC NULLS LAST" in body


def test_source_url_is_the_rad_link_and_text_is_as_filed():
    body = _strip(_chunk("company_events"))
    cols = body[body.index("RETURNS TABLE ("): body.index("\n)\nLANGUAGE")]
    assert "source_url" in cols
    assert "g.link_download" in body
    for col in ("e.categoria", "e.tipo", "e.especie", "e.assunto"):
        assert col in body
    # CVM's labels are served and matched verbatim, never case-folded.
    assert "upper(" not in _body("company_events").lower()


def test_unknown_category_lists_what_is_held():
    body = _strip(_chunk("company_events"))
    assert "SELECT DISTINCT e.categoria FROM public.cia_event e" in body
    assert "'unknown IPE category %; cia_event holds: %'" in body


# ---------------------------------------------------------------------------
# macro_series: the registry is the pipeline's non-inflation list
# ---------------------------------------------------------------------------


def _registry() -> dict[str, int]:
    chunk = SQL26[SQL26.index("CREATE OR REPLACE FUNCTION api.macro_registry()"):]
    chunk = chunk[: chunk.index("$$;")]
    return {lab: int(code) for lab, code in re.findall(r"\('(\w+)',\s*(\d+),", chunk)}


def test_registry_is_sgs_series_minus_the_inflation_set():
    from src.pipeline.bacen_pipeline import INFLATION_SERIES, SGS_SERIES

    expected = {k: v for k, v in SGS_SERIES.items() if k not in INFLATION_SERIES}
    assert _registry() == expected


def test_coverage_row_reads_exactly_the_registry_codes():
    cov = _coverage()
    seg = cov[cov.index("SELECT 'macro_series'::text"):]
    seg = seg[: seg.index("UNION ALL")]
    codes = {int(c) for c in re.search(r"series_code IN \(([^)]*)\)", seg).group(1).split(",")}
    assert codes == set(_registry().values())
    assert "'*bacen_sgs*'::text" in seg


def test_macro_series_refuses_ipca_and_lists_what_exists():
    body = _strip(_chunk("macro_series"))
    assert "FROM api.inflation_registry() i" in body
    assert "api.inflation serves the IPCA set" in body
    assert "'unknown macro series %; macro_series serves: %'" in body
    assert "FROM public.bacen_sgs b" in body and "b.series_code = v_code" in body


def test_units_ride_on_every_row():
    for name in ("macro_series", "ptax"):
        cols = _strip(_chunk(name))
        cols = cols[cols.index("RETURNS TABLE ("): cols.index("\n)\nLANGUAGE")]
        assert re.search(r"^\s*unit\s+TEXT", cols, re.M), name


# ---------------------------------------------------------------------------
# ptax
# ---------------------------------------------------------------------------


def test_ptax_serves_buy_and_sell_as_published():
    body = _strip(_chunk("ptax"))
    assert "x.buy_rate AS b, x.sell_rate AS s" in body
    assert "'unknown PTAX currency %; bacen_ptax holds: %'" in body
    assert "SELECT DISTINCT x.currency FROM public.bacen_ptax x" in body


def test_ptax_currencies_are_the_pipelines():
    from src.pipeline.bacen_pipeline import PTAX_CURRENCIES

    head = _chunk("ptax")
    for c in PTAX_CURRENCIES:
        assert c in head


# ---------------------------------------------------------------------------
# coverage(), catalog, SDK
# ---------------------------------------------------------------------------


def test_coverage_reports_all_three_with_their_own_landed_source():
    cov = _coverage()
    for dataset, entity in (("company_events", "*cia_ipe*"), ("macro_series", "*bacen_sgs*"),
                            ("ptax", "*bacen_ptax*")):
        seg = cov[cov.index(f"SELECT '{dataset}'::text"):]
        seg = seg[: seg.index("UNION ALL") if "UNION ALL" in seg else len(seg)]
        assert f"'{entity}'::text" in seg, dataset
    assert "l.entity = 'cia_aberta' AND l.doc_type = 'ipe'" in cov
    assert "l.entity = 'bacen' AND l.doc_type = 'ptax'" in cov
    seg = cov[cov.index("SELECT 'company_events'::text"):]
    assert "NULL::date" in seg[:400], "no completeness model for company filings"
    assert "2015" in seg[: seg.index("UNION ALL")]


def test_catalog_publishes_the_three():
    from serve.catalog import CATALOG_VERSION, CONSTRAINTS, catalog_payload

    assert CATALOG_VERSION >= 36
    payload = catalog_payload()
    for name in SERVED:
        assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"
        assert name in payload["limits"]["page"]["all"]
        assert name in payload["limits"]["page"]["functions"]["raise_only"]
    assert any(c.startswith("COMPANY EVENTS ARE IPE FILINGS AS FILED") for c in CONSTRAINTS)
    assert any(c.startswith("MACRO SERIES AND PTAX ARE SERVED AS BACEN PUBLISHES THEM") for c in CONSTRAINTS)


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
    c.company_events("PETR4", start="2026-01-01", category="Fato Relevante")
    c.macro_series("CDI", start="2026-01-01")
    c.ptax("USD", end="2026-09-01")
    for name in SERVED:
        declared = set(re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M))
        assert set(sent[name]) == declared, name
    assert sent["company_events"]["p_id"] == "PETR4"
    assert sent["ptax"]["p_to"] == "2026-09-01"
