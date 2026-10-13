"""Pin docs/reference/API.md to the catalog's postgrest set, offline (#889).

``tests/test_mcp_contract.py`` and ``tests/test_endpoint_manifest.py`` pin the
MCP tools and the catalog's ``postgrest`` map to the granted ``api.*`` surface.
Nothing pinned the human reference: API.md named 46 of 81 endpoints. Its
"Endpoint index" section lists every route of that map; this test fails while
one is missing, so a new endpoint cannot ship without its API.md line.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import catalog_payload

API_MD = Path(__file__).resolve().parents[1] / "docs" / "reference" / "API.md"


def _listed() -> set[str]:
    """The routes the '## Endpoint index' section of API.md lists, one per line."""
    text = API_MD.read_text(encoding="utf-8")
    m = re.search(r"^## Endpoint index\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, "API.md has no '## Endpoint index' section"
    return set(re.findall(r"^(?:GET|POST) /rest/v1/\S+$", m.group(1), re.M))


def _missing(routes: dict[str, str], listed: set[str]) -> list[str]:
    return sorted(f"{k}: {r}" for k, r in routes.items() if r not in listed)


def test_every_postgrest_route_is_in_the_api_md_index():
    missing = _missing(catalog_payload()["postgrest"], _listed())
    assert not missing, (
        "add these routes to the '## Endpoint index' section of "
        f"docs/reference/API.md: {missing}"
    )


def test_an_unlisted_route_is_reported():
    """The check is not vacuous: a route the index does not list is caught."""
    routes = {**catalog_payload()["postgrest"], "not_shipped": "POST /rest/v1/rpc/not_shipped"}
    assert _missing(routes, _listed()) == ["not_shipped: POST /rest/v1/rpc/not_shipped"]
