"""No published surface says IBOV11 "prints only on expiry days" (catalog v49).

It did through 2024 (12 prints a year). It printed weekly in 2025 and has printed
on nearly every session since December 2025: 181 of the 187 sessions of 2026.
What never changed, and is the reason index_history refuses it, is that none of
those prints equals the official close (mean difference 0.18%, up to 1.07%). The
research notes under docs/reference/research/ are dated records and keep what
they measured; they carry an addendum instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from serve.catalog import CATALOG_VERSION, catalog_payload

ROOT = Path(__file__).resolve().parents[1]

#: Every place a caller or an agent reads the description.
PUBLISHED = [
    "src/store/analytical/29_api_index.sql",
    "api-docs/guides/research.mdx",
    "api-docs/cotahist-dictionary.mdx",
    "sdk/silo_client/client.py",
    "docs/reference/research/README.md",
]

STALE = re.compile(
    r"prints?\s+(?:only\s+)?on\s+expiry\s+days(?:\s+only)?|"
    r"expiry\s+days\s+only|"
    r"~monthly\s+on\s+option\s+expiry",
    re.I,
)


def test_the_catalog_no_longer_calls_ibov11_an_expiry_day_series():
    assert CATALOG_VERSION >= 49
    text = " ".join(catalog_payload()["constraints"])
    assert not STALE.search(DATED.sub("", _flat(text))), STALE.search(text)
    assert "never the official close" in text
    assert "since December 2025" in text


def _flat(text: str) -> str:
    """One line of prose: comment markers and line breaks do not hide a phrase."""
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*--\s?", "", text))


# The true, dated statement is allowed: "printed on expiry days only through 2024".
DATED = re.compile(r"printed on expiry days only,?\s*(?:12 a year,?\s*)?through 2024", re.I)


def test_the_sql_header_the_guide_the_dictionary_and_the_sdk_say_the_same():
    for rel in PUBLISHED:
        flat = DATED.sub("", _flat((ROOT / rel).read_text(encoding="utf-8")))
        hit = STALE.search(flat)
        assert not hit, (rel, hit.group(0) if hit else None)
        assert "through 2024" in _flat((ROOT / rel).read_text(encoding="utf-8")) or rel.endswith("client.py"), rel


def test_the_substitution_rule_is_unchanged():
    sql = (ROOT / "src/store/analytical/29_api_index.sql").read_text(encoding="utf-8")
    assert "IBOV11" in sql and "never the" in sql
    # the refusal still names the options settlement code as no substitute
    assert "BOVA11 (an ETF) or IBOV11" in sql


def test_the_research_note_carries_the_dated_addendum_with_the_numbers():
    note = (ROOT / "docs/reference/research/ibovespa-source.md").read_text(encoding="utf-8")
    assert "Addendum 2026-10-01" in note
    for fact in ("181 of the 187 sessions", "0.18%", "1.07%", "161,669", "161,125.37"):
        assert fact in note, fact
