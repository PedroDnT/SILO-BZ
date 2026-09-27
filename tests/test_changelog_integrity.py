"""The changelog is one markdown table, and merge conflicts kept corrupting it.

`docs/planning/CHANGELOG.md` is appended to by almost every branch, so almost
every branch resolves a conflict in it. Resolving that conflict by keeping both
sides concatenates two whole tables — second header row and all — and the
duplicate rows are invisible in review because the file is long and the rows are
paragraphs.

It had accumulated **37 duplicate rows out of 113** and a second `| Date |`
header before anyone noticed, and the second header renders as a data row. This
file makes the next occurrence a red build instead of silent accretion.

Two properties deliberately NOT asserted, because asserting them would cause
the damage they look like they prevent:

* **Rows are compared on EXACT text, never fuzzily.** Ten rows legitimately
  share a date and a branch with differing text (one branch landing several
  changes on one day). A "same date+branch must be unique" rule would call
  those duplicates and invite someone to delete real history.
* **Cell padding is not normalised.** Some rows are column-aligned and some are
  not. It renders identically, and reflowing 85 rows to fix it would bury the
  next real changelog diff in whitespace churn.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).resolve().parents[1] / "docs/planning/CHANGELOG.md"


def _lines() -> list[str]:
    return CHANGELOG.read_text(encoding="utf-8").split("\n")


def _rows() -> list[str]:
    """Data rows. Every one starts with a `| 20xx-` date cell."""
    return [line for line in _lines() if line.startswith("| 20")]


def _is_header(line: str) -> bool:
    return line.lstrip().startswith("| Date")


def test_there_are_no_duplicate_rows() -> None:
    counts = collections.Counter(_rows())
    dupes = {row: n for row, n in counts.items() if n > 1}
    assert not dupes, (
        f"{sum(n - 1 for n in dupes.values())} duplicate changelog row(s) across "
        f"{len(dupes)} distinct entries. This is what resolving a CHANGELOG.md "
        "merge conflict by keeping both sides looks like. Keep ONE copy of each "
        "row — do not delete a whole block, because a block can contain rows the "
        "other side never had.\nFirst offender: "
        + next(iter(dupes))[:160]
    )


def test_there_is_exactly_one_table_header() -> None:
    headers = [line for line in _lines() if _is_header(line)]
    assert len(headers) == 1, (
        f"found {len(headers)} `| Date |` header rows; expected 1. A second "
        "header is a concatenated second table, and markdown renders it as a "
        "data row rather than a header."
    )


def test_rows_are_newest_first() -> None:
    dates = [row.split("|")[1].strip() for row in _rows()]
    out_of_order = [
        (i, dates[i], dates[i + 1])
        for i in range(len(dates) - 1)
        if dates[i] < dates[i + 1]
    ]
    assert not out_of_order, (
        "changelog rows must run newest first; an ascending jump means a block "
        f"was appended rather than merged in date order: {out_of_order[:3]}"
    )


def test_every_row_has_a_date_a_branch_and_a_change() -> None:
    """A row must carry all three cells filled in."""
    thin = []
    for row in _rows():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 3 or not all(cells[:3]):
            thin.append(row[:120])
    assert not thin, f"row(s) missing a date, branch or change: {thin}"


def test_every_row_has_exactly_three_cells() -> None:
    """An unescaped `|` in prose splits a row into phantom columns.

    Markdown splits on every `|` not written as `\\|`, including inside code
    spans, so `date|id|metric` in a row renders as extra cells. Two historical
    rows did exactly that until they were escaped; this keeps a third from
    landing.
    """
    wide = []
    for row in _rows():
        cells = re.split(r"(?<!\\)\|", row.strip().strip("|"))
        if len(cells) != 3:
            wide.append((len(cells), row[:120]))
    assert not wide, (
        "changelog row(s) split into the wrong number of cells; escape any "
        f"`|` inside the prose as `\\|`: {wide[:3]}"
    )


@pytest.mark.parametrize("cell", [1, 2])
def test_dates_and_branches_are_well_formed(cell: int) -> None:
    bad = []
    for row in _rows():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        value = cells[cell - 1]
        if cell == 1 and not (len(value) == 10 and value[4] == value[7] == "-"):
            bad.append(value)
        if cell == 2 and (" " in value.strip() and "/" not in value):
            bad.append(value)
    assert not bad, f"malformed cell {cell}: {bad[:5]}"
