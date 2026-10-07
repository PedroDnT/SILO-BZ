"""The declared endpoint contract against what the SQL actually does.

`serve/catalog.py` DECLARES, by hand, which set-returning functions refuse
above one 1000-row page and which of those hand back a `p_after` cursor
(`_CAPPED_FUNCTIONS`, `_PAGED_CURSORS`); `limits.page` and the counts in the
row-cap constraint are derived from those two. `serve/endpoint_manifest.py`
READS the same facts out of `src/store/analytical/*.sql`. Intent and
introspection are kept apart on purpose, and this file is where they meet: a
function that starts refusing without being declared, a declared function the
SQL no longer caps, or a cursor that appears or vanishes, fails here.
"""

from __future__ import annotations

import re

import pytest

from scripts import gen_openapi
from serve import catalog
from serve.catalog import LIMITS, catalog_payload
from serve.endpoint_manifest import granted_functions, granted_views, manifest

PAGE = LIMITS["page"]
ENDPOINTS = manifest()
PUBLIC = {name: e for name, e in ENDPOINTS.items() if e.granted}


def _cap_constraint() -> str:
    hits = [c for c in catalog.CONSTRAINTS if "Row caps" in c]
    assert len(hits) == 1, "expected exactly one row-cap constraint"
    return hits[0]


# ---------------------------------------------------------------------------
# The parser itself. An empty or partial parse would make every check below
# vacuous.
# ---------------------------------------------------------------------------


def test_the_manifest_sees_the_whole_surface():
    assert len(PUBLIC) >= 70, f"only {len(PUBLIC)} public endpoints parsed"
    assert ENDPOINTS["panel"].kind == "rpc" and ENDPOINTS["quotes"].kind == "view"
    assert ENDPOINTS["panel"].file == "19_api_contract.sql"
    assert ENDPOINTS["portfolio_equivalents"].file == "31_api_portfolio.sql"
    assert "p_after" in ENDPOINTS["panel"].params
    assert ENDPOINTS["option_chain"].params[0] == "p_prefix"
    # Helpers are parsed but never granted.
    for helper in ("assert_row_cap", "caller_tier", "parse_date_cursor"):
        assert ENDPOINTS[helper].kind == "rpc" and not ENDPOINTS[helper].granted
    assert set(granted_functions()) == {n for n, e in PUBLIC.items() if e.kind == "rpc"}
    assert set(granted_views()) >= {n for n, e in PUBLIC.items() if e.kind == "view"}


# ---------------------------------------------------------------------------
# Declared intent against introspection.
# ---------------------------------------------------------------------------


def test_declared_capped_functions_are_exactly_the_ones_the_sql_caps():
    declared = PAGE["all"]
    assert len(declared) == len(set(declared)), "a function is declared twice"
    refusing = {n for n, e in PUBLIC.items() if e.refuses}
    assert set(declared) - refusing == set(), (
        "declared as refusing above one page, but the SQL never calls "
        f"api.assert_row_cap: {sorted(set(declared) - refusing)}"
    )
    assert refusing - set(declared) == set(), (
        "the SQL refuses above one page but limits.page.all does not say so: "
        f"{sorted(refusing - set(declared))}"
    )
    for name in declared:
        assert ENDPOINTS[name].kind == "rpc" and ENDPOINTS[name].granted, name


def test_declared_cursors_are_exactly_the_ones_the_sql_takes():
    paged = set(PAGE["functions"]["paged"])
    raise_only = PAGE["functions"]["raise_only"]
    assert paged == {n for n, e in PUBLIC.items() if e.pages}, (
        "limits.page.functions.paged must list exactly the capped functions "
        "that declare p_after"
    )
    assert set(raise_only) == {n for n, e in PUBLIC.items() if e.raise_only}
    assert paged.isdisjoint(raise_only)
    assert paged | set(raise_only) == set(PAGE["all"])


def test_tier_ceilings_are_exactly_the_functions_that_clamp_by_tier():
    """A function that branches on api.caller_tier() without refusing lowers
    p_limit silently; LIMITS.tiers must publish its ceiling for both tiers."""
    clamping = {n for n, e in PUBLIC.items() if e.tier_clamps}
    for tier in ("anon", "authenticated"):
        published = {
            key[: -len("_rows")] for key in LIMITS["tiers"][tier] if key.endswith("_rows")
        }
        assert published == clamping, (tier, sorted(published ^ clamping))


def test_the_postgrest_map_is_the_granted_surface():
    """Every POST route is a granted function, every GET route a granted view,
    and nothing granted is missing (catalog is the map itself)."""
    seen = set()
    for key, route in catalog_payload()["postgrest"].items():
        verb, path = route.split(" ", 1)
        if verb == "POST":
            assert path.startswith("/rest/v1/rpc/"), (key, route)
            name, kind = path[len("/rest/v1/rpc/"):], "rpc"
        else:
            assert verb == "GET" and path.startswith("/rest/v1/"), (key, route)
            name, kind = path[len("/rest/v1/"):], "view"
        assert name in PUBLIC, f"{route} names nothing granted to anon/authenticated"
        assert PUBLIC[name].kind == kind, f"{route}: api.{name} is a {PUBLIC[name].kind}"
        seen.add(name)
    assert set(PUBLIC) - seen == {"catalog"}, sorted(set(PUBLIC) - seen - {"catalog"})


# ---------------------------------------------------------------------------
# The prose that restates the counts and names.
# ---------------------------------------------------------------------------


def test_cap_constraint_counts_follow_the_declaration():
    c = _cap_constraint()
    n_screens = sum(1 for n in PAGE["all"] if n.startswith("screen_"))
    assert f"all {catalog._number_word(len(PAGE['all']))} —" in c
    assert f"the {catalog._number_word(n_screens)} screen_* functions" in c
    assert f"{catalog._number_word(len(PAGE['functions']['paged'])).upper()} OF THEM PAGE" in c


def test_cap_constraint_names_every_capped_function():
    c = _cap_constraint()
    listed = c[c.index(" — panel"): c.index("(`limits.page.all`)")]
    named = set(re.findall(r"\b[a-z][a-z0-9_]*\b", listed))
    for name in PAGE["all"]:
        if name.startswith("screen_"):
            continue  # counted as "the ten screen_* functions"
        assert name in named, f"the cap constraint does not name {name}"
    pages = c[c.index("OF THEM PAGE with p_after:"): c.index("Send p_after")]
    for name in PAGE["functions"]["paged"]:
        assert name in pages, f"the cap constraint does not say {name} pages"


@pytest.mark.parametrize("n,word", [
    (0, "zero"), (5, "five"), (10, "ten"), (19, "nineteen"), (20, "twenty"),
    (40, "forty"), (55, "fifty-five"), (99, "ninety-nine"),
])
def test_number_word(n, word):
    assert catalog._number_word(n) == word


def test_openapi_intro_counts_match_the_declaration():
    """gen_openapi.py writes the counts into openapi.json's description by
    hand; they must say what the catalog declares."""
    intro = gen_openapi._INFO_DESCRIPTION
    n_all = len(PAGE["all"])
    n_paged = len(PAGE["functions"]["paged"])
    n_clamp = sum(1 for e in PUBLIC.values() if e.tier_clamps)
    assert f"{catalog._number_word(n_all).capitalize()} set-returning functions" in intro
    assert f"{catalog._number_word(n_paged).capitalize()} of them" in intro
    assert f"the other {catalog._number_word(n_all - n_paged)} ask" in intro
    assert f"{catalog._number_word(n_clamp).capitalize()} other functions" in intro
