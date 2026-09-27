"""The FIDC structure tabs served as filed (catalog v31, backlog B3).

fidc_tranches reads cvm_fidc_tranche (tabs X_2/X_3/X_6) and
cvm_fidc_tranche_flows (tab X_4); fidc_aging reads cvm_fidc_aging (tab VI).
These pin what makes them honest rather than merely present: every schema
column reaches the caller exactly once, nothing is derived or coalesced to
zero, the free-text TP_OPER label is never bucketed, neither tab is
inner-joined away, the row cap refuses instead of trimming, and the one
limit a caller would otherwise misread — history begins in 2025 because CVM
publishes no archive — is on the coverage rows, the catalog and the docs.

Offline: the SQL is checked as text. The apply is the sql-compile CI job's.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "src/store/analytical/19_api_contract.sql").read_text(encoding="utf-8")
SCHEMA = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL.index(f"REVOKE ALL ON FUNCTION api.{name}(", start)
    return SQL[start:end]


def _stripped(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _table_columns(table: str) -> list[str]:
    start = SCHEMA.index(f"CREATE TABLE IF NOT EXISTS {table} (")
    block = SCHEMA[start:SCHEMA.index(");", start)]
    cols = re.findall(r"^\s+([a-z_0-9]+)\s+(?:NUMERIC|TEXT|DATE|INT|JSONB|BIGSERIAL|TIMESTAMPTZ)", block, re.M)
    return [c for c in cols if c not in ("id", "raw", "fetched_at")]


# ---------------------------------------------------------------------------
# fidc_tranches
# ---------------------------------------------------------------------------

def test_tranches_serve_every_tranche_column_exactly_once():
    body = _stripped(_body("fidc_tranches"))
    for col in _table_columns("cvm_fidc_tranche"):
        if col in ("cnpj", "period", "classe_serie"):
            continue
        assert body.count(f"t.{col}") == 1, f"cvm_fidc_tranche.{col} must reach the caller exactly once"
    for col in ("vl_total", "qt_cota", "tp_oper"):
        assert f"f.{col}" in body, f"cvm_fidc_tranche_flows.{col} missing from flows"


def test_tranches_need_a_fund_and_refuse_without_one():
    body = _body("fidc_tranches")
    assert "IF v_cnpj IS NULL THEN" in body
    assert "USING ERRCODE = '22023'" in body
    assert "p_cnpj   TEXT," in body, "p_cnpj has no default: it is required"


def test_tranches_never_inner_join_one_tab_away():
    body = _stripped(_body("fidc_tranches"))
    keys = body[body.index("WITH keys AS ("):body.index("page (")]
    assert "FROM public.cvm_fidc_tranche t" in keys and "FROM public.cvm_fidc_tranche_flows f" in keys
    assert re.search(r"\bUNION\b", keys), "the key set is the union of both tabs"
    assert "LEFT JOIN public.cvm_fidc_tranche t" in body
    assert "LEFT JOIN LATERAL" in body
    assert "(t.cnpj IS NOT NULL)" in body, "tranche_filed says which rows had no X_2 row"
    assert not re.search(r"\bINNER\s+JOIN\b|\bJOIN\s+public\.cvm_fidc_tranche\b", body.replace("LEFT JOIN", ""))


def test_tranche_flows_keep_the_filed_label_and_are_never_bucketed():
    body = _stripped(_body("fidc_tranches"))
    assert "jsonb_agg(" in body and "jsonb_build_object(" in body
    assert "'tp_oper', NULLIF(f.tp_oper, '')" in body, "ingest's '' blank is served as null"
    upper = body.upper()
    for bucketing in ("%CAPT%", "%RESG%", "%AMORT%", "ILIKE", " LIKE "):
        assert bucketing not in upper, f"flows must not be bucketed by label ({bucketing})"
    assert "COALESCE(JSONB_AGG" not in upper and "'[]'" not in body, (
        "no flows filed is NULL, never an invented empty array"
    )


def test_tranches_derive_nothing():
    body = _stripped(_body("fidc_tranches")).upper()
    assert "PR_DESEMP_REAL -" not in body and "- T.PR_DESEMP" not in body, "no performance gap"
    assert "SUM(" not in body and "AVG(" not in body
    assert not re.search(r"COALESCE\([^)]*,\s*0\)", body), "a blank is never coerced to zero"
    assert "SENIOR" not in body, "no senior/subordinated classification"


def test_tranches_return_shape():
    body = _body("fidc_tranches")
    shape = body[body.index("RETURNS TABLE ("):body.index("LANGUAGE plpgsql")]
    cols = re.findall(r"^\s+([a-z_]+)\s+[A-Z]", shape, re.M)
    assert cols == [
        "cnpj", "period", "classe_serie", "quotas", "quota_value", "return_month",
        "performance_expected", "performance_realised", "tranche_filed", "flows",
    ]
    assert "flows                JSONB" in shape and "tranche_filed        BOOLEAN" in shape


def test_tranche_series_filter_is_exact_on_both_tabs():
    body = _stripped(_body("fidc_tranches"))
    assert "t.classe_serie = v_series" in body and "f.classe_serie = v_series" in body


# ---------------------------------------------------------------------------
# fidc_aging
# ---------------------------------------------------------------------------

def test_aging_unpivots_every_bucket_exactly_once():
    body = _stripped(_body("fidc_aging"))
    for col in _table_columns("cvm_fidc_aging"):
        if col in ("cnpj", "period"):
            continue
        assert body.count(f"a.{col})") == 1, f"cvm_fidc_aging.{col} must be served exactly once"
    rows = re.findall(r"\(\s*\d+, '(to_maturity|overdue|overdue_total)',", body)
    assert rows.count("to_maturity") == 10 and rows.count("overdue") == 10
    assert rows.count("overdue_total") == 1


def test_aging_bands_follow_the_legacy_headers():
    # TAB_VI_VL_PRAZO_1_30 / _31_60 / ... / _MAIS_1080: the bands CVM's own
    # older column names spell out.
    body = _stripped(_body("fidc_aging"))
    bands = re.findall(r"'(to_maturity|overdue)',\s+'([^']+)',\s+(\d+),\s+(\d+|NULL)", body)
    expected = [("1-30", "1", "30"), ("31-60", "31", "60"), ("61-90", "61", "90"),
                ("91-120", "91", "120"), ("121-150", "121", "150"), ("151-180", "151", "180"),
                ("181-360", "181", "360"), ("361-720", "361", "720"), ("721-1080", "721", "1080"),
                (">1080", "1081", "NULL")]
    for kind in ("to_maturity", "overdue"):
        assert [b[1:] for b in bands if b[0] == kind] == expected, kind


def test_aging_total_is_the_filed_one_never_a_sum():
    body = _stripped(_body("fidc_aging"))
    assert "'overdue_total', 'TOTAL',     NULL, NULL, 'vl_total_inad',       a.vl_total_inad" in body
    upper = body.upper()
    assert "SUM(" not in upper and " + " not in body, "overdue_total is CVM's filed total"
    assert not re.search(r"COALESCE\([^)]*,\s*0\)", upper), "a blank bucket is null, never zero"


def test_aging_needs_a_fund():
    body = _body("fidc_aging")
    assert "IF v_cnpj IS NULL THEN" in body and "USING ERRCODE = '22023'" in body


# ---------------------------------------------------------------------------
# Both: definer hygiene, grants, row cap, coverage, catalog, SDK, docs
# ---------------------------------------------------------------------------

SIGS = {"fidc_tranches": "TEXT, DATE, DATE, TEXT", "fidc_aging": "TEXT, DATE, DATE"}


def test_definer_hygiene_and_grants():
    for fn, sig in SIGS.items():
        head = _body(fn)[: _body(fn).index("AS $fn$")]
        assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
        assert f"REVOKE ALL ON FUNCTION api.{fn}({sig}) FROM PUBLIC;" in SQL
        assert f"GRANT EXECUTE ON FUNCTION api.{fn}({sig})\n    TO anon, authenticated;" in SQL
        assert re.search(rf"GRANT EXECUTE ON FUNCTION api\.{fn}\({re.escape(sig)}\)\s+TO silo_api;", SQL)
        assert f"COMMENT ON FUNCTION api.{fn}({sig}) IS" in SQL


def test_every_relation_is_schema_qualified():
    for fn in SIGS:
        body = _stripped(_body(fn))
        for rel in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", body):
            assert rel.startswith(("public.", "api.")) or rel in ("page", "keys", "LATERAL"), (
                f"{fn}: {rel} is unqualified under search_path = ''"
            )


def test_row_cap_refuses_and_does_not_tier():
    for fn in SIGS:
        body = _stripped(_body(fn))
        assert "LIMIT 1001" in body and "LIMIT 1000" in body
        assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{fn}')" in body
        assert "caller_tier" not in body, "raise-only: no silent tier clamp"
        assert "p_after" not in body and "p_limit" not in body


def test_coverage_reports_both_with_the_2025_limit():
    cov = _body("coverage")
    for row, table in (("fidc_tranches", "cvm_fidc_tranche"), ("fidc_aging", "cvm_fidc_aging")):
        assert f"'{row}'::text" in cov, f"coverage lacks the {row} row"
        seg = cov[cov.index(f"SELECT '{row}'::text"):]
        seg = seg[: seg.index("UNION ALL")]
        assert f"FROM public.{table} " in seg
        assert "2025-01" in seg and "no equivalent member" in seg and "not a gap" in seg
        assert "public.latest_complete_period('fidc')" in seg
        assert "'fidc'::text" in seg, "landed_at comes from the fidc ingest"


def test_the_catalog_names_both_and_states_the_limit():
    from serve.catalog import CATALOG_VERSION, catalog_payload

    cat = catalog_payload()
    assert CATALOG_VERSION >= 31
    for fn in SIGS:
        assert cat["postgrest"][fn] == f"POST /rest/v1/rpc/{fn}"
        assert fn in cat["limits"]["page"]["all"]
        assert fn in cat["limits"]["page"]["functions"]["raise_only"]
        assert f"{fn}_rows" not in cat["limits"]["tiers"]["anon"], "raise-only, not tier-clamped"
    text = " ".join(cat["constraints"])
    assert "FIDC TRANCHES AND AGING BEGIN IN 2025" in text
    assert "verbatim" in text and "overdue_total" in text and "not a sum of the bands" in text
    embedded = SQL[SQL.index("SELECT $json$") + len("SELECT $json$"):SQL.index("$json$::jsonb")]
    assert json.loads(embedded)["version"] == CATALOG_VERSION


def test_the_sdk_wraps_both_with_the_sql_argument_names():
    from sdk.silo_client.client import KNOWN_CATALOG_VERSION, SiloClient

    assert KNOWN_CATALOG_VERSION >= 31
    sent = {}

    class _Probe(SiloClient):
        def __init__(self):  # no network, no config
            pass

        def _rpc(self, name, args):
            sent[name] = args
            return []

    c = _Probe()
    c.fidc_tranches("05.754.060/0001-13", start="2025-01-01", series="Subclasse Senior 1")
    c.fidc_aging("05754060000113", end="2026-06-30")
    assert set(sent["fidc_tranches"]) == {"p_cnpj", "p_from", "p_to", "p_series"}
    assert sent["fidc_tranches"]["p_series"] == "Subclasse Senior 1"
    assert set(sent["fidc_aging"]) == {"p_cnpj", "p_from", "p_to"}
    for fn in SIGS:
        args = re.findall(r"^\s+(p_\w+)\s", _body(fn)[: _body(fn).index("RETURNS")], re.M)
        assert set(args) == set(sent[fn]), f"SDK and SQL disagree on {fn}'s arguments"


def test_openapi_publishes_both_with_p_cnpj_required():
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    for fn in SIGS:
        op = spec["paths"][f"/rpc/{fn}"]["post"]
        body = op["requestBody"]["content"]["application/json"]["schema"]
        assert body["required"] == ["p_cnpj"]
        assert "**Row cap.**" in op["description"] and "does not page" in op["description"]
        assert "Tier ceiling" not in op["description"]
        assert op["tags"] == ["FIDC"]


def test_docs_register_the_page_and_the_inventory_moves_the_rows():
    page = ROOT / "api-docs/fidc-structure.mdx"
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    assert "fidc_tranches" in text and "fidc_aging" in text and "2025" in text
    nav = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    assert "api-docs/fidc-structure" in json.dumps(nav)
    assert "api-docs/fidc-structure.md" in (ROOT / "llms.txt").read_text(encoding="utf-8")
    inv = (ROOT / "docs/DATA_INVENTORY.md").read_text(encoding="utf-8")
    served = inv[inv.index("### Served"):inv.index("### Held and not served")]
    held = inv[inv.index("### Held and not served"):inv.index("### Not served by design")]
    for table in ("cvm_fidc_tranche", "cvm_fidc_tranche_flows", "cvm_fidc_aging"):
        assert f"`{table}`" in served, f"{table} belongs in Served"
        assert f"`{table}`" not in held, f"{table} is no longer a candidate"
