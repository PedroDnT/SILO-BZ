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


def _nav_pages() -> list[str]:
    docs = json.loads((ROOT / "docs.json").read_text())
    pages: list[str] = []
    for group in docs["navigation"]["groups"]:
        pages.extend(group.get("pages") or [])
    return pages


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


def test_mdx_does_not_link_the_unpublished_docs_folder():
    bad = []
    for path in [ROOT / "index.mdx", *sorted((ROOT / "api-docs").glob("*.mdx"))]:
        text = path.read_text()
        if "](/docs/" in text or 'href="/docs/' in text:
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, "MDX still links to /docs/… which Mintlify does not publish: " + ", ".join(bad)
