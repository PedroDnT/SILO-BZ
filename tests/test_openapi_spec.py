"""The guard whose absence let five granted endpoints ship undocumented.

`api.short_interest`, `api.short_interest_by_sector`, `api.investor_flow`,
`api.lending_trades` and `api.lending_participants` were granted to `anon` and
served live for weeks with no page describing them. Nothing checked, because
the only docs test (`test_mintlify_nav.py`) asks whether nav paths resolve to
files — never whether the documented surface equals the granted one.

This file closes that class. It is deliberately OFFLINE, like the rest of the
suite: it parses the GRANT statements out of the analytical SQL and asserts, in
both directions, that the committed `openapi.json` describes exactly the
objects the SQL grants.

    granted in SQL but absent from the spec  -> a new endpoint shipped undocumented
    present in the spec but absent from SQL  -> the spec describes something that no
                                                longer exists (a 404 in the docs)

`scripts/gen_openapi.py` generates the spec from the live Postgres catalog, so
the two agree by construction the moment it is re-run. These tests are what
fails in CI when somebody edits the SQL and does not.

The parse is regex-based and comment-stripped, matching the house style already
used by `tests/test_api_contract_sql.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "openapi.json"
ANALYTICAL = ROOT / "src" / "store" / "analytical"

# Every analytical file that grants something in schema `api`. 19 is the
# contract proper; 20 and 21 are the B3 BDI views added later — and 20/21 are
# exactly the files whose grants outran the docs, so a test that only read 19
# would have missed the incident it exists to prevent. Glob rather than list,
# so a 22_*.sql is covered the day it lands.
SQL_FILES = sorted(ANALYTICAL.glob("[0-9][0-9]_*.sql"))

# The two tiers that make an object PUBLIC. `silo_api` is the serve/ role and
# `service_role` bypasses the boundary; neither publishes anything, so a grant
# to those alone is not a documented endpoint.
PUBLIC_ROLES = ("anon", "authenticated")


def _strip_comments(sql: str) -> str:
    """Drop `--` line comments and /* */ blocks so prose never matches."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def _grantee_list_is_public(grantees: str) -> bool:
    names = {g.strip().strip('"').lower() for g in grantees.split(",")}
    return bool(names & set(PUBLIC_ROLES))


_GRANT_SELECT = re.compile(
    r"\bGRANT\s+SELECT\s+ON\s+(?P<objects>.+?)\s+TO\s+(?P<grantees>[^;]+);",
    re.IGNORECASE | re.DOTALL,
)

_GRANT_EXECUTE = re.compile(
    r"\bGRANT\s+EXECUTE\s+ON\s+FUNCTION\s+(?P<objects>.+?)\s+TO\s+(?P<grantees>[^;]+);",
    re.IGNORECASE | re.DOTALL,
)

_API_RELATION = re.compile(r"\bapi\.(?P<name>[a-z_][a-z0-9_]*)\b", re.IGNORECASE)
_API_FUNCTION = re.compile(r"\bapi\.(?P<name>[a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)


def granted_views() -> set[str]:
    found: set[str] = set()
    for path in SQL_FILES:
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for m in _GRANT_SELECT.finditer(sql):
            if not _grantee_list_is_public(m.group("grantees")):
                continue
            objects = m.group("objects")
            # `GRANT SELECT ON FUNCTION` is not a thing; a SELECT grant naming
            # a parenthesised object would be a table function, which schema
            # api does not use. Take the bare relation names.
            for rel in _API_RELATION.finditer(objects):
                found.add(rel.group("name").lower())
    return found


def granted_functions() -> set[str]:
    found: set[str] = set()
    for path in SQL_FILES:
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for m in _GRANT_EXECUTE.finditer(sql):
            if not _grantee_list_is_public(m.group("grantees")):
                continue
            for fn in _API_FUNCTION.finditer(m.group("objects")):
                found.add(fn.group("name").lower())
    return found


@pytest.fixture(scope="module")
def spec() -> dict:
    assert SPEC_PATH.is_file(), (
        "openapi.json is missing. Regenerate it with "
        "POSTGRES_URL=... python scripts/gen_openapi.py > openapi.json"
    )
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spec_views(spec) -> set[str]:
    return {p.lstrip("/") for p in spec["paths"] if not p.startswith("/rpc/")}


@pytest.fixture(scope="module")
def spec_functions(spec) -> set[str]:
    return {p[len("/rpc/"):] for p in spec["paths"] if p.startswith("/rpc/")}


# ---------------------------------------------------------------------------
# The two directions. These are the tests that had to exist.
# ---------------------------------------------------------------------------


def test_every_granted_view_is_in_the_spec(spec_views):
    """A view granted to anon/authenticated but absent here shipped undocumented."""
    missing = sorted(granted_views() - spec_views)
    assert not missing, (
        "granted api.* views missing from openapi.json (this is exactly how "
        "short_interest / investor_flow / lending_trades shipped live and "
        "undocumented): " + ", ".join(missing) + ". Regenerate with "
        "POSTGRES_URL=... python scripts/gen_openapi.py > openapi.json"
    )


def test_every_granted_function_is_in_the_spec(spec_functions):
    missing = sorted(granted_functions() - spec_functions)
    assert not missing, (
        "granted api.* functions missing from openapi.json: " + ", ".join(missing)
        + ". Regenerate with POSTGRES_URL=... python scripts/gen_openapi.py > openapi.json"
    )


def test_no_spec_view_has_vanished_from_sql(spec_views):
    """The other direction: a documented endpoint that the SQL no longer grants."""
    stale = sorted(spec_views - granted_views())
    assert not stale, (
        "openapi.json documents api.* views that no SQL GRANTs to anon/authenticated "
        "— the docs would 404 a reader: " + ", ".join(stale)
    )


def test_no_spec_function_has_vanished_from_sql(spec_functions):
    stale = sorted(spec_functions - granted_functions())
    assert not stale, (
        "openapi.json documents api.* functions that no SQL GRANTs to "
        "anon/authenticated: " + ", ".join(stale)
    )


# ---------------------------------------------------------------------------
# Signature drift. Presence is not enough: a function whose arguments changed
# is as wrong as one that vanished, and reads worse because the page looks
# right.
# ---------------------------------------------------------------------------


def _sql_function_signatures() -> dict[str, list[str]]:
    """Argument NAMES per api function, read off CREATE FUNCTION in the SQL."""
    sigs: dict[str, list[str]] = {}
    pattern = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+api\.(?P<name>[a-z_][a-z0-9_]*)\s*"
        r"\((?P<args>.*?)\)\s*\n\s*RETURNS",
        re.IGNORECASE | re.DOTALL,
    )
    for path in SQL_FILES:
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for m in pattern.finditer(sql):
            args = m.group("args")
            names = re.findall(r"(?:^|,)\s*(p_[a-z0-9_]+)\s", args, re.IGNORECASE)
            sigs[m.group("name").lower()] = [n.lower() for n in names]
    return sigs


def test_spec_request_bodies_match_the_sql_signatures(spec, spec_functions):
    """Each RPC's request body carries exactly the SQL's parameter names."""
    sigs = _sql_function_signatures()
    drift: list[str] = []
    for name in sorted(spec_functions):
        if name not in sigs:
            continue  # presence is covered by the tests above
        body = spec["paths"][f"/rpc/{name}"]["post"]["requestBody"]
        props = body["content"]["application/json"]["schema"].get("properties", {})
        in_spec = sorted(props)
        in_sql = sorted(sigs[name])
        if in_spec != in_sql:
            drift.append(f"{name}: spec {in_spec} != sql {in_sql}")
    assert not drift, (
        "openapi.json request bodies have drifted from the CREATE FUNCTION "
        "signatures:\n  " + "\n  ".join(drift)
    )


# ---------------------------------------------------------------------------
# The behavioural contract. The spec is worth little if it describes the
# endpoints but lies about what they do at the edges, which is where callers
# actually get hurt.
# ---------------------------------------------------------------------------

# Read off serve/catalog.py LIMITS["page"], the authority for these numbers.
REFUSING_FUNCTIONS = {
    "panel",
    "quote_history",
    "fund_nav",
    "option_history",
    "termo_history",
    "financials",
    "company_financials",
    "anbima_classes",
}
PAGED_FUNCTIONS = {"panel", "quote_history", "fund_nav"}


def test_refusing_functions_say_they_refuse(spec):
    """The eight capped functions must state the 22023, not imply trimming."""
    silent = []
    for name in sorted(REFUSING_FUNCTIONS):
        desc = spec["paths"][f"/rpc/{name}"]["post"]["description"]
        if "22023" not in desc or "1000" not in desc:
            silent.append(name)
    assert not silent, (
        "these functions raise SQLSTATE 22023 above the 1000-row page but the "
        "spec does not say so: " + ", ".join(silent)
    )


def test_paged_functions_expose_the_cursor(spec):
    missing = []
    for name in sorted(PAGED_FUNCTIONS):
        props = spec["paths"][f"/rpc/{name}"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]["properties"]
        if "p_after" not in props:
            missing.append(name)
    assert not missing, "paged functions with no p_after in the spec: " + ", ".join(missing)


def test_fund_nav_paging_requires_entity_type(spec):
    """fund_nav's cursor is a bare period — unique only within one family.

    385 CNPJs file under both fi and fidc in the same month, so paging without
    p_entity_type is ambiguous and the SQL raises rather than answer wrongly.
    A reader who does not learn this from the page learns it from a 22023.
    """
    desc = spec["paths"]["/rpc/fund_nav"]["post"]["description"]
    assert "p_entity_type" in desc, "fund_nav page does not mention p_entity_type"
    props = spec["paths"]["/rpc/fund_nav"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["properties"]
    assert "p_entity_type" in props


def test_tier_split_is_documented(spec):
    """Signing in raises ceilings; it must never widen the object set."""
    schemes = spec["components"]["securitySchemes"]
    assert schemes["apikey"]["in"] == "header"
    assert schemes["apikey"]["name"] == "apikey"
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert "authenticated" in schemes["bearerAuth"]["description"]
    # The bearer token is OPTIONAL: apikey alone is a valid security option.
    assert {"apikey": []} in spec["security"]


def test_error_bodies_carry_the_sqlstate(spec):
    err = spec["components"]["schemas"]["Error"]
    assert "code" in err["properties"], "PostgREST error body must expose `code` (the SQLSTATE)"
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert "400" in op["responses"], f"{method.upper()} {path} documents no 400"
            assert "401" in op["responses"], f"{method.upper()} {path} documents no 401"


def test_spec_is_openapi_31(spec):
    assert spec["openapi"].startswith("3.1"), spec["openapi"]
    assert spec["servers"][0]["url"].endswith("/rest/v1")


def test_spec_version_tracks_the_catalog(spec):
    """info.version is api.catalog()'s CATALOG_VERSION, not an invented number."""
    from serve.catalog import CATALOG_VERSION

    assert spec["info"]["version"] == str(CATALOG_VERSION), (
        f"openapi.json was generated against catalog v{spec['info']['version']} but "
        f"serve/catalog.py is now v{CATALOG_VERSION} — regenerate the spec."
    )
