"""`llms.txt` is the page index agents read first, so it must not go stale.

It is a hand-written file listing published pages, which is precisely the shape
of thing that drifts: within an hour of it being authored, #247 added four
pages and the index silently stopped being complete. Nothing caught that,
because nothing compared the index to the navigation.

This guard fails in BOTH directions, the same way `test_openapi_spec.py`
guards the OpenAPI surface against the SQL grants:

  * a page in `docs.json`'s navigation that `llms.txt` does not list — an
    agent reading the index never learns the page exists;
  * a page `llms.txt` lists that has no file behind it — the index points at
    a 404, which is worse than omitting it.

Offline, like the rest of the suite: it reads the repository, never the
published site.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLMS = ROOT / "llms.txt"

#: Every `https://<host>/<page>.md` reference in the index.
_PAGE_REF = re.compile(r"mintlify\.site/([A-Za-z0-9_./-]+)\.md")


def _llms_text() -> str:
    return LLMS.read_text()


def _nav_pages() -> list[str]:
    docs = json.loads((ROOT / "docs.json").read_text())
    pages: list[str] = []
    for group in docs["navigation"]["groups"]:
        pages.extend(group.get("pages") or [])
    return pages


def _page_file(page: str) -> Path | None:
    for ext in (".mdx", ".md"):
        candidate = ROOT / f"{page}{ext}"
        if candidate.is_file():
            return candidate
    return None


def test_llms_txt_exists_and_has_the_llms_txt_shape():
    """Title, one-line blockquote summary, then sectioned bullets."""
    text = _llms_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0].startswith("# "), "llms.txt must open with an H1 title"
    assert any(ln.startswith("> ") for ln in lines[:5]), (
        "llms.txt must carry a blockquote summary near the top"
    )
    assert text.count("\n## ") >= 3, "llms.txt groups its entries under sections"


def test_every_nav_page_is_listed_in_llms_txt():
    listed = _llms_text()
    missing = [p for p in _nav_pages() if f"/{p}.md" not in listed]
    assert not missing, (
        "pages in docs.json navigation that llms.txt does not list "
        "(an agent reading the index never learns they exist): "
        + ", ".join(missing)
    )


def test_llms_txt_never_points_at_a_page_that_does_not_exist():
    dangling = [ref for ref in _PAGE_REF.findall(_llms_text())
                if _page_file(ref) is None]
    assert not dangling, (
        "llms.txt lists pages with no .mdx/.md file behind them "
        "(the index would 404): " + ", ".join(dangling)
    )


def test_no_published_page_is_unreachable_from_the_navigation():
    """A page under api-docs/ that is not in docs.json's nav is orphaned.

    Mintlify serves a page that is absent from the navigation — `/skill.md`
    proves it — so an orphaned page's URL resolves and nothing 404s. That is
    exactly what makes it easy to miss: nothing links to it, it is absent from
    the sidebar, and a reader only finds it by already knowing the path.

    `test_mintlify_nav.py` guards the other direction (a nav entry whose file
    does not exist). This one closes the pair, so a page cannot ship written
    but unreachable — the same defect shape as an endpoint shipping granted
    but undocumented.

    Root-level Markdown is deliberately excluded: `skill.md` is published for
    agents and stays out of the sidebar on purpose (see the test below), and
    the rest is repository documentation that `.mintignore` excludes.
    """
    nav = set(_nav_pages())
    # docs.json names pages repo-relative and without an extension.
    on_disk = {
        p.relative_to(ROOT).with_suffix("").as_posix()
        for p in (ROOT / "api-docs").rglob("*.mdx")
    }
    on_disk.add("index")

    orphaned = sorted(on_disk - nav)
    assert not orphaned, (
        "published pages missing from docs.json navigation — the URL resolves "
        "but nothing links to them and they are absent from the sidebar: "
        + ", ".join(orphaned)
    )


def test_skill_md_is_listed_and_is_not_mintignored():
    """skill.md is published deliberately, though it is not in the navigation.

    It is the agent loader: api-docs/agents.mdx and llms.txt both link to it by
    URL, so `/skill.md` has to resolve. `.mintignore` excludes directories and
    now also the root-level files that are repository documentation rather than
    published pages — skill.md is deliberately NOT among them.
    """
    assert "/skill.md" in _llms_text(), "llms.txt must list skill.md"
    assert (ROOT / "skill.md").is_file()

    ignored = {
        line.split("#", 1)[0].strip().rstrip("/")
        for line in (ROOT / ".mintignore").read_text().splitlines()
        if line.split("#", 1)[0].strip()
    }
    assert "skill.md" not in ignored, (
        "skill.md is published on purpose (agents.mdx and llms.txt link to it "
        "by URL); mintignoring it would 404 those links"
    )
