"""The sidebar reads broad → granular → operational, and three copies agree.

Evidence sorts the sidebar alphabetically unless a page sets `sidebar_position`.
The order is a product decision (2026-09-15: industry and backdrop, then one page
per asset class, then houses / funds / rankings / screens, then the pipeline), so
it is pinned here and the two prose copies — dashboard/README.md and the
"Pages" tables on index.md — must list the routes in the same order.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "dashboard" / "pages"

ORDER = [
    # Industry backdrop and market structure first: /short and /flows sit with
    # /markets because they are all about the exchange, not about funds.
    "industry", "macro", "markets", "short", "flows",
    "fi", "fidc", "fii", "securit", "etf",
    "managers", "fund", "performance", "suspicious", "dormant",
    "ops",
]


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.name} has no frontmatter"
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def test_every_page_but_the_index_has_a_unique_sidebar_position():
    seen: dict[int, str] = {}
    for path in sorted(PAGES.glob("*.md")):
        fm = _frontmatter(path)
        if path.stem == "index":
            assert "sidebar_position" not in fm, "the entry point is not ordered"
            continue
        assert "sidebar_position" in fm, f"{path.name}: no sidebar_position"
        pos = int(fm["sidebar_position"])
        assert pos not in seen, f"{path.name} and {seen[pos]} share position {pos}"
        seen[pos] = path.name
    assert sorted(seen) == list(range(1, len(ORDER) + 1))


def test_sidebar_positions_follow_the_decided_order():
    got = sorted(
        (int(_frontmatter(PAGES / f"{stem}.md")["sidebar_position"]), stem)
        for stem in ORDER
    )
    assert [stem for _, stem in got] == ORDER


def _route_order_in(text: str) -> list[str]:
    """Routes in the order their first table row mentions them."""
    seen: list[str] = []
    for m in re.finditer(r"\| .*?\(/(\w+)\)|`/(\w+)`", text):
        stem = m.group(1) or m.group(2)
        if stem in ORDER and stem not in seen:
            seen.append(stem)
    return seen


def test_index_pages_tables_list_routes_in_sidebar_order():
    text = (PAGES / "index.md").read_text(encoding="utf-8")
    section = text[text.index("## Pages"):text.index("## What Is in the Warehouse")]
    assert _route_order_in(section) == ORDER


def test_readme_routes_table_lists_routes_in_sidebar_order():
    text = (ROOT / "dashboard" / "README.md").read_text(encoding="utf-8")
    section = text[text.index("## Pages"):text.index("### Page conventions")]
    assert _route_order_in(section) == ORDER
