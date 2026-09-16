"""The lending/flow pages must survive their own empty sources.

fact_short_interest_daily and fact_investor_flow_daily are the only relations in
this warehouse that CANNOT be backfilled: B3 keeps ~21 business days and
publishes no archive, so on a fresh deploy — or any time the daily fetch has not
run — they are empty. The sources already handle that with the union-all
sentinel (a zero-row Evidence source writes a 0-byte parquet that kills the whole
build), but the sentinel is a row of NULLs, and a chart handed one fails two
different ways, both seen in production on 2026-09-16:

    Error: Column 'trade_date' is entirely null. Column must contain at least
           one non-null value.                       <- sentinel reaches a date axis
    Error in Line Chart: Dataset is empty ...        <- page SQL filters the
                                                        sentinel away -> 0 rows

So every component bound to one of those sources has to sit behind an {#if}.
These tests pin that, because the failure is invisible offline: it only appears
in Evidence's SSR during a real build.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "dashboard" / "pages"

# page -> the query names that resolve to a non-backfillable source and must be
# guarded. `adtv` is deliberately absent: it reads b3_cotahist, which is always
# populated.
GUARDED = {
    "short.md": {"headline", "top_float", "top_sir", "top_rate",
                 "by_sector", "history", "basis_split"},
    "flows.md": {"headline", "flow_main", "flow_summary", "monthly_vista"},
}
UNGUARDED_OK = {"flows.md": {"adtv"}}


def _text(page: str) -> str:
    return (PAGES / page).read_text(encoding="utf-8")


@pytest.mark.parametrize("page", sorted(GUARDED))
def test_guards_are_balanced_and_never_nested(page):
    """An unbalanced or nested {#if} is a Svelte compile error at build time."""
    s = _text(page)
    tokens = [m.group(0) for m in re.finditer(r"\{#if |\{:else\}|\{/if\}", s)]
    depth = 0
    for t in tokens:
        if t.startswith("{#if"):
            depth += 1
        elif t == "{/if}":
            depth -= 1
        assert depth in (0, 1), f"{page}: nested or unbalanced guard"
    assert depth == 0, f"{page}: unclosed guard"
    assert s.count("{#if ") == s.count("{:else}") == s.count("{/if}"), page


def _guarded_spans(s: str) -> list[tuple[int, int]]:
    """Character ranges covered by the {#if} branch of each guard."""
    spans = []
    for m in re.finditer(r"\{#if ", s):
        end = s.index("{:else}", m.start())
        spans.append((m.start(), end))
    return spans


@pytest.mark.parametrize("page", sorted(GUARDED))
def test_every_non_backfillable_binding_sits_behind_a_guard(page):
    s = _text(page)
    spans = _guarded_spans(s)
    for query in sorted(GUARDED[page]):
        hits = list(re.finditer(r"data=\{" + query + r"\}", s))
        assert hits, f"{page}: no component binds data={{{query}}} — did it get renamed?"
        for h in hits:
            assert any(a <= h.start() < b for a, b in spans), (
                f"{page}: data={{{query}}} is not inside an {{#if}} guard. Its source "
                f"can be a single all-NULL sentinel row, which crashes the Evidence "
                f"build (see this file's docstring)."
            )


@pytest.mark.parametrize("page,queries", sorted(UNGUARDED_OK.items()))
def test_populated_sources_are_not_needlessly_guarded(page, queries):
    """A guard on an always-populated source would hide a real regression."""
    s = _text(page)
    spans = _guarded_spans(s)
    for query in sorted(queries):
        for h in re.finditer(r"data=\{" + query + r"\}", s):
            assert not any(a <= h.start() < b for a, b in spans), (
                f"{page}: data={{{query}}} reads an always-populated table; "
                f"guarding it would mask a genuine empty result."
            )


@pytest.mark.parametrize("page", sorted(GUARDED))
def test_the_else_branch_explains_why_rather_than_showing_zero(page):
    """An empty state that reads as 'zero' is the fabrication this repo forbids."""
    s = _text(page)
    for m in re.finditer(r"\{:else\}(.*?)\{/if\}", s, re.S):
        branch = m.group(1)
        # Prose in these branches wraps, so a phrase can straddle a newline.
        # Compare on collapsed whitespace or this test breaks on a reflow.
        flat = " ".join(branch.split())
        assert "<Alert" in branch, f"{page}: an {{:else}} branch renders no explanation"
        assert "no archive" in flat or "no rows for past months" in flat, (
            f"{page}: the empty state must say WHY the series is short "
            f"(B3 keeps no archive), not just that it is empty."
        )
        assert not re.search(r"\b0\b|zero", flat, re.I), (
            f"{page}: the empty state must not present a zero."
        )
