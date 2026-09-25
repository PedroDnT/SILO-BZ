"""The filing-behaviour screens in schema `api` (25_api_filing_screens.sql, v37).

Offline, like the rest of the suite: the SQL text, the catalog and the SDK are
read from the repository and pinned to each other. What this file keeps true:

* SIGNALS, NOT VERDICTS — the rules of 23_api_screens.sql: every row carries
  `screen` and `params`, no column is a score, the COMMENT leads with the
  disclaimer and the catalog says what else produces the same row.
* The house serving rules from 19: SECURITY DEFINER with an empty pinned
  search_path, REVOKE from PUBLIC then GRANT to anon/authenticated (no
  silo_api, as for every screen), one page plus one row and
  api.assert_row_cap refusing above it, 22023 on bad input, nothing clamped.
* FUND IDENTITY IS A cnpjFundo LINK. The FNET screens never compare, join or
  filter on fund_name.
* "LATE" CITES ITS RULE. The deadline is Resolução CVM 175's text, cited on
  every row and in the catalog, and months before each family's adaptation
  deadline are not measured.
* "SILENT" READS CVM's DEEP TABLES (dim_fund) against the honest anchor
  latest_complete_period, never today, and only for registry-active funds.
* The defaults live in three places at once: the SQL DEFAULTs, catalog
  SCREENS[...]["params"] and the SDK wrappers' arguments.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SQL25_PATH = ANALYTICAL / "25_api_filing_screens.sql"
SQL25 = SQL25_PATH.read_text(encoding="utf-8")
APPLY = ROOT / "scripts" / "apply_analytical.sh"
CLIENT = ROOT / "sdk" / "silo_client" / "client.py"

# api function -> catalog SCREENS key
SCREENS = {
    "screen_restatements": "restatements",
    "screen_late_filers": "late_filers",
    "screen_silent_filers": "silent_filers",
}
FNET_SCREENS = ("screen_restatements", "screen_late_filers")


def _strip(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _chunk(name: str) -> str:
    start = SQL25.index(f"CREATE OR REPLACE FUNCTION api.{name}(")
    end = SQL25.index("$fn$;", start) + len("$fn$;")
    return SQL25[start:end]


def _signature(name: str) -> str:
    chunk = _chunk(name)
    return chunk[chunk.index("(") + 1: chunk.index("\nRETURNS")]


def _arg_defaults(name: str) -> dict:
    out = {}
    for line in _strip(_signature(name)).splitlines():
        m = re.match(r"\s*(p_\w+)\s+\w+\s+DEFAULT\s+([^,\s]+)", line)
        if not m:
            continue
        raw = m.group(2)
        out[m.group(1)] = None if raw.upper() == "NULL" else float(raw)
    return out


def _arg_types(name: str) -> str:
    types = []
    for line in _strip(_signature(name)).splitlines():
        m = re.match(r"\s*p_\w+\s+(\w+)", line)
        if m:
            types.append(m.group(1))
    return ", ".join(types)


def _result_columns(name: str) -> list[str]:
    chunk = _strip(_chunk(name))
    body = chunk[chunk.index("RETURNS TABLE (") + len("RETURNS TABLE ("): chunk.index("\n)\nLANGUAGE")]
    return [ln.split()[0] for ln in body.splitlines() if ln.strip()]


def _comment(name: str) -> str:
    m = re.search(rf"COMMENT ON FUNCTION api\.{name}\([^)]*\) IS\s*'(.*?)';\n", SQL25, re.S)
    assert m, f"{name} has no COMMENT"
    return m.group(1)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_apply_script_globs_the_file_after_its_dependencies():
    script = APPLY.read_text(encoding="utf-8")
    assert "src/store/analytical/[0-9][0-9]_*.sql" in script
    ordered = sorted(p.name for p in ANALYTICAL.glob("[0-9][0-9]_*.sql"))
    i = ordered.index("25_api_filing_screens.sql")
    for dep in ("01_dim_fund.sql", "04_fact_fund_monthly.sql", "19_api_contract.sql", "24_api_fnet.sql"):
        assert i > ordered.index(dep), dep


def test_file_is_one_transaction_and_guards_its_dependencies():
    body = _strip(SQL25)
    assert re.search(r"^\s*BEGIN\s*;", body, re.M)
    assert re.search(r"COMMIT\s*;\s*$", body.strip())
    assert "to_regprocedure('api.assert_row_cap(bigint, boolean, text)') IS NULL" in body
    assert "to_regclass('public.fnet_document') IS NULL" in body
    assert "to_regclass('public.dim_fund') IS NULL" in body
    assert "to_regprocedure('public.latest_complete_period(text)') IS NULL" in body


def test_exactly_the_three_screens_are_created():
    created = set(re.findall(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+api\.(\w+)\(", _strip(SQL25)))
    assert created == set(SCREENS)


# ---------------------------------------------------------------------------
# House privilege model and row cap
# ---------------------------------------------------------------------------


def test_restatements_has_no_per_fund_lateral_over_the_window():
    """Production, v38: a LATERAL that rescanned `docs` once per flagged fund
    ran past anon's 3 s statement timeout at the defaults. The tipoFundo
    labels come from one grouped join (`tipo`) instead."""
    body = _strip(_chunk("screen_restatements"))
    assert "LATERAL" not in body.upper()
    assert re.search(r"\btipo\s+AS\s*\(", body)
    assert re.search(r"LEFT\s+JOIN\s+tipo\s+tf\s+ON\s+tf\.cnpj\s*=\s*fl\.cnpj", body)


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_definer_with_an_empty_pinned_search_path(name):
    head = _chunk(name)
    head = head[: head.index("AS $fn$")]
    assert "SECURITY DEFINER" in head
    assert "SET search_path = ''" in head


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_relation_is_schema_qualified(name):
    body = _strip(_chunk(name))
    body = body[body.index("RETURN QUERY"):]
    body = re.sub(r"'[^']*'", "''", body)                       # string literals
    body = re.sub(r"extract\(\s*(year|month)\s+FROM", "extract(", body, flags=re.I)
    for rel in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][\w.]*)", body, re.I):
        if rel.lower() in {"lateral", "docs", "per_fund", "flagged", "page", "informes",
                           "months", "measured", "reg", "fam", "silent", "tipo"}:
            continue
        assert rel.startswith(("public.", "api.")), f"{name}: unqualified relation {rel}"


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_revoked_from_public_then_granted_to_the_client_roles(name):
    sig = f"api.{name}({_arg_types(name)})"
    assert f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC;" in SQL25, sig
    assert f"GRANT EXECUTE ON FUNCTION {sig} TO anon, authenticated;" in SQL25, sig


def test_silo_api_gets_no_screen_grant():
    assert "silo_api" not in _strip(SQL25)


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_refuses_above_one_page_instead_of_trimming(name):
    body = _strip(_chunk(name))
    assert re.search(r"\bLIMIT\s+1001\b", body)
    assert re.search(r"\bLIMIT\s+1000\s*;", body)
    assert f"api.assert_row_cap((SELECT count(*) FROM page), FALSE, '{name}')" in body
    assert "p_after" not in body


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_bad_arguments_raise_and_nothing_is_clamped(name):
    body = _strip(_chunk(name))
    assert "ERRCODE = '22023'" in body
    assert "LEAST(" not in body and "GREATEST(" not in body
    # Every argument that has bounds is checked for NULL too.
    for arg in re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M):
        if arg in ("p_end",):
            continue
        assert re.search(rf"{arg} IS (NOT )?NULL", body), f"{name}: {arg} is never validated"


# ---------------------------------------------------------------------------
# Signals, not verdicts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_every_row_carries_screen_and_params(name):
    assert _result_columns(name)[-2:] == ["screen", "params"]
    assert f"'{SCREENS[name]}'::text" in _strip(_chunk(name))


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_params_echo_exactly_the_function_arguments(name):
    body = _strip(_chunk(name))
    call = body[body.index("jsonb_build_object("):]
    call = call[: call.index("\n    FROM page g")]
    keys = re.findall(r"'(p_\w+)'\s*,\s*(p_\w+)", call)
    assert keys and all(k == v for k, v in keys)
    declared = re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M)
    assert sorted(k for k, _ in keys) == sorted(declared)


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_no_column_is_a_score_and_columns_are_english(name):
    for col in _result_columns(name):
        assert not re.search(r"score|suspic|fraud|risk_level|verdict|violation", col, re.I), col
    portuguese = {"versao", "modalidade", "situacao", "dt_patrim_liq", "vl_patrim_liq",
                  "entity_type", "status", "delivered", "reference_raw"}
    assert not portuguese & set(_result_columns(name)), name


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_comment_leads_with_signal_not_verdict_and_says_what_else(name):
    c = _comment(name)
    assert c.startswith("SIGNAL, NOT A VERDICT.")
    assert "same" in c and ("pattern" in c or "row" in c), "the comment must say what else looks the same"


# ---------------------------------------------------------------------------
# Fund identity: a cnpjFundo link, never a name.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FNET_SCREENS)
def test_fnet_screens_know_a_fund_only_by_its_cnpjfundo_link(name):
    body = _strip(_chunk(name))
    assert "l.filter_name = 'cnpjFundo'" in body
    # fund_name may be SELECTED as FNET's label; it is never compared.
    assert not re.search(r"fund_name\s*(=|<>|!=|ILIKE|LIKE|~|IN\s*\()", body, re.I)
    assert not re.search(r"(=|ILIKE|LIKE)\s*\w+\.fund_name", body, re.I)


def test_silent_screen_joins_by_cnpj_and_family_not_by_name():
    body = _strip(_chunk("screen_silent_filers"))
    assert "r.cnpj = s.cnpj" in body and "r.entity_type = s.entity_type" in body
    assert "l.filter_value = g.cnpj" in body
    assert not re.search(r"fund_name\s*(=|ILIKE|LIKE)", body, re.I)


# ---------------------------------------------------------------------------
# Restatements
# ---------------------------------------------------------------------------


def test_restatements_count_versions_above_one_and_split_by_modalidade():
    body = _strip(_chunk("screen_restatements"))
    assert "dc.versao > 1 AND dc.modalidade = 'RE'" in body
    assert "dc.versao > 1 AND dc.modalidade = 'RC'" in body
    assert "p_modalidade NOT IN ('RE', 'RC')" in body
    # Both thresholds, not either.
    assert "f.n_restated >= p_min_restatements" in body
    assert "AND 100.0 * f.n_restated / f.n_docs >= p_min_rate_pct" in body


# ---------------------------------------------------------------------------
# Late filers: the rule is cited, the window respects the adaptation deadlines
# ---------------------------------------------------------------------------

FIDC_CITE = "Resolução CVM 175, Anexo Normativo II, art. 27, III"
FII_CITE = "Resolução CVM 175, Anexo Normativo III, art. 36, I"


def test_late_filers_cite_the_rule_on_every_row():
    body = _strip(_chunk("screen_late_filers"))
    assert "deadline_rule" in _result_columns("screen_late_filers")
    assert FIDC_CITE in body and FII_CITE in body
    c = _comment("screen_late_filers")
    assert "Anexo Normativo II, art. 27, III" in c and "Anexo Normativo III, art. 36, I" in c


def test_late_filers_deadline_is_month_end_plus_fifteen_calendar_days():
    body = _strip(_chunk("screen_late_filers"))
    assert "((m.ref_month + interval '1 month')::date - 1 + 15)" in body
    assert "ms.days_past >= p_min_days_late" in body


def test_late_filers_measure_only_after_each_familys_adaptation_deadline():
    body = _strip(_chunk("screen_late_filers"))
    assert "CASE x.fam WHEN 'fidc' THEN DATE '2024-12-01' ELSE DATE '2025-07-01' END" in body
    assert "IF v_to < DATE '2024-12-01' THEN" in body


def test_late_filers_use_the_first_delivery_of_an_original_informe():
    body = _strip(_chunk("screen_late_filers"))
    assert "d.versao = 1" in body
    assert "btrim(d.tipo_documento) = 'Informe Mensal Estruturado'" in body
    assert "min(i.delivered_at) AS first_delivery" in body


def test_late_filers_family_is_a_link_or_an_unambiguous_registry_row():
    body = _strip(_chunk("screen_late_filers"))
    assert "HAVING count(DISTINCT r.entity_type) = 1" in body
    assert "WHERE x.fam IS NOT NULL" in body


def test_catalog_carries_the_citation():
    from serve.catalog import SCREENS as CAT

    rule = CAT["late_filers"]["deadline_rule"]
    assert rule["fidc"].startswith(FIDC_CITE)
    assert rule["fii"].startswith(FII_CITE)
    assert "2024-12" in rule["fidc"] and "2025-07" in rule["fii"]


# ---------------------------------------------------------------------------
# Silent filers: CVM's deep tables, the honest anchor, active registry rows
# ---------------------------------------------------------------------------


def test_silent_filers_anchor_on_complete_through_not_today():
    body = _strip(_chunk("screen_silent_filers"))
    assert "public.latest_complete_period(f.fam)" in body
    assert "FROM public.dim_fund d" in body
    assert "CURRENT_DATE" not in body
    assert "r.is_active IS TRUE" in body
    assert "('fi'), ('fidc'), ('fii'), ('fiagro')" in body, "FIP files annually and is not screened"


# ---------------------------------------------------------------------------
# Defaults: SQL == catalog; SDK sends only declared parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCREENS))
def test_catalog_entry_matches_the_sql(name):
    from serve.catalog import catalog_payload

    payload = catalog_payload()
    entry = payload["screens"][SCREENS[name]]
    assert entry["function"] == name
    assert entry["dashboard"] is None, "no page runs these screens"
    assert len(entry["meaning"]) > 200
    published = entry["params"]
    sql = _arg_defaults(name)
    assert set(published) == set(sql)
    for arg, value in sql.items():
        got = published[arg]
        assert (got is None and value is None) or float(got) == value, (name, arg)
    assert set(entry.get("filters", {})) <= set(sql)
    assert payload["postgrest"][name] == f"POST /rest/v1/rpc/{name}"
    assert name in payload["limits"]["page"]["all"]
    assert name in payload["limits"]["page"]["functions"]["raise_only"]


def test_catalog_version_and_sdk_agree():
    from sdk.silo_client.client import KNOWN_CATALOG_VERSION
    from serve.catalog import CATALOG_VERSION

    assert CATALOG_VERSION >= 37
    assert KNOWN_CATALOG_VERSION == CATALOG_VERSION


def test_sdk_wraps_each_screen():
    tree = ast.parse(CLIENT.read_text(encoding="utf-8"))
    wrapped = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_rpc" and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert set(SCREENS) <= wrapped


def test_sdk_screen_wrappers_send_exactly_the_sql_parameters():
    from sdk.silo_client.client import SiloClient

    sent = {}

    class Stub(SiloClient):
        def __init__(self):  # no network
            pass

        def _rpc(self, fn, body, page=False):
            sent[fn] = body
            return []

    c = Stub()
    c.screen_restatements(months=6, modalidade="RC")
    c.screen_late_filers(family="fidc", end="2026-08-01")
    c.screen_silent_filers(family="fii")
    for name in SCREENS:
        declared = set(re.findall(r"^\s*(p_\w+)\s", _strip(_signature(name)), re.M))
        assert set(sent[name]) == declared, name
    assert sent["screen_restatements"]["p_modalidade"] == "RC"
    assert sent["screen_late_filers"]["p_end"] == "2026-08-01"
