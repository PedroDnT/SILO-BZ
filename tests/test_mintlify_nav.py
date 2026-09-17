"""Mintlify nav pages must exist on disk and not sit under .mintignore.

The public docs portal 404s a sidebar item when docs.json points at a path
the MDX parser never publishes (that is how /docs/DATA_INVENTORY broke).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ignored_prefixes() -> list[str]:
    prefixes: list[str] = []
    for raw in (ROOT / ".mintignore").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("!"):
            continue
        prefixes.append(line.rstrip("/"))
    return prefixes


def _nav_groups() -> list[dict]:
    return json.loads((ROOT / "docs.json").read_text())["navigation"]["groups"]


def _nav_pages() -> list[str]:
    pages: list[str] = []
    for group in _nav_groups():
        pages.extend(group.get("pages") or [])
    return pages


def _openapi_refs() -> list[tuple[str, str]]:
    """(group name, spec path) for every group that renders an OpenAPI spec.

    A group may carry `openapi` instead of `pages`: Mintlify then generates one
    sidebar entry per operation in the spec. That is a nav path too, and it
    breaks the same way — a spec Mintlify cannot read publishes an empty
    section with no build error.
    """
    refs: list[tuple[str, str]] = []
    for group in _nav_groups():
        spec = group.get("openapi")
        if not spec:
            continue
        for entry in [spec] if isinstance(spec, str) else spec:
            refs.append((group.get("group", "?"), entry))
    return refs


def test_every_nav_page_is_a_real_mintlify_file():
    ignored = _ignored_prefixes()
    missing = []
    ignored_hits = []
    for page in _nav_pages():
        if any(page == p or page.startswith(p + "/") for p in ignored):
            ignored_hits.append(page)
            continue
        if not any((ROOT / f"{page}{ext}").is_file() for ext in (".mdx", ".md")):
            missing.append(page)
    assert not ignored_hits, (
        "docs.json points at mintignored paths (sidebar 404): " + ", ".join(ignored_hits)
    )
    assert not missing, "docs.json pages with no .mdx/.md file: " + ", ".join(missing)


def test_every_group_has_pages_or_an_openapi_spec():
    """A group with neither publishes an empty, unclickable sidebar heading."""
    empty = [
        g.get("group", "?")
        for g in _nav_groups()
        if not g.get("pages") and not g.get("openapi")
    ]
    assert not empty, "docs.json groups with no pages and no openapi spec: " + ", ".join(empty)


def test_openapi_specs_in_nav_are_real_readable_files():
    """`"openapi": "openapi.json"` must resolve, parse, and describe something.

    A remote https:// spec is Mintlify's to fetch; only local paths are ours
    to check.
    """
    ignored = _ignored_prefixes()
    for group, ref in _openapi_refs():
        if ref.startswith(("http://", "https://")):
            continue
        rel = ref.lstrip("/")
        assert not any(rel == p or rel.startswith(p + "/") for p in ignored), (
            f"docs.json group {group!r} points at a mintignored spec: {ref}"
        )
        path = ROOT / rel
        assert path.is_file(), f"docs.json group {group!r} references a missing spec: {ref}"
        spec = json.loads(path.read_text())
        assert spec.get("openapi", "").startswith("3."), (
            f"{ref} is not an OpenAPI 3.x document"
        )
        assert spec.get("paths"), f"{ref} declares no paths — the section would render empty"


def test_mdx_does_not_link_the_unpublished_docs_folder():
    bad = []
    for path in [ROOT / "index.mdx", *sorted((ROOT / "api-docs").glob("*.mdx"))]:
        text = path.read_text()
        if "](/docs/" in text or 'href="/docs/' in text:
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, "MDX still links to /docs/… which Mintlify does not publish: " + ", ".join(bad)
