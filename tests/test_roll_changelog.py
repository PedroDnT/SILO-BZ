"""scripts/roll_changelog.py moves old changelog rows, and only moves them.

The live `docs/planning/CHANGELOG.md` keeps the newest rows; the rest go,
unchanged, into a frozen `docs/archive/changelog/<oldest>_to_<newest>.md`. The
push hook reads both, so the property that matters is that every row is still
somewhere, word for word, in the same order.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "roll_changelog", Path(__file__).resolve().parents[1] / "scripts/roll_changelog.py")
roll_changelog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(roll_changelog)

HEAD = "# Changelog\n\n| Date | Branch | Change |\n| --- | --- | --- |\n"


def row(n: int) -> str:
    """Newest first: n=0 is the newest, one day apart, with a few same-day rows."""
    day = 30 - n // 2
    return f"| 2026-08-{day:02d} | claude/b{n} | **Change {n}.** Why, with a `code | pipe` escaped as \\| here. |\n"


@pytest.fixture
def tree(tmp_path: Path):
    live = tmp_path / "docs/planning/CHANGELOG.md"
    live.parent.mkdir(parents=True)
    rows = [row(n) for n in range(10)]
    live.write_text(HEAD + "".join(rows), encoding="utf-8")
    return live, tmp_path / "docs/archive/changelog", rows


def table_rows(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if line.startswith("| 20")]


def test_it_keeps_the_newest_rows_and_moves_the_rest_unchanged(tree):
    live, archive, rows = tree
    target = roll_changelog.roll(live, archive, keep=4)
    assert table_rows(live) == rows[:4]
    assert table_rows(target) == rows[4:]
    assert table_rows(live) + table_rows(target) == rows  # nothing lost, same order


def test_the_archive_file_is_named_for_its_oldest_and_newest_row(tree):
    live, archive, rows = tree
    target = roll_changelog.roll(live, archive, keep=4)
    assert target.name == "2026-08-26_to_2026-08-28.md"
    text = target.read_text(encoding="utf-8")
    assert text.count("| Date | Branch | Change |") == 1 and "Frozen" in text


def test_the_live_file_keeps_its_header_and_points_at_the_archive(tree):
    live, archive, _ = tree
    roll_changelog.roll(live, archive, keep=4)
    text = live.read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n\n") and text.count("| Date | Branch | Change |") == 1
    assert "docs/archive/changelog/" in text.split("| Date")[0]


def test_nothing_to_roll_changes_nothing(tree):
    live, archive, _ = tree
    before = live.read_bytes()
    assert roll_changelog.roll(live, archive, keep=10) is None
    assert live.read_bytes() == before and not archive.exists()


def test_a_second_run_is_a_no_op(tree):
    live, archive, _ = tree
    roll_changelog.roll(live, archive, keep=4)
    before = live.read_bytes()
    assert roll_changelog.roll(live, archive, keep=4) is None
    assert live.read_bytes() == before and len(list(archive.iterdir())) == 1


def test_a_dry_run_writes_nothing(tree):
    live, archive, _ = tree
    before = live.read_bytes()
    assert roll_changelog.roll(live, archive, keep=4, dry_run=True) is None
    assert live.read_bytes() == before and not archive.exists()


def test_it_never_overwrites_a_frozen_archive_file(tree):
    live, archive, _ = tree
    archive.mkdir(parents=True)
    (archive / "2026-08-26_to_2026-08-28.md").write_text("frozen\n", encoding="utf-8")
    before = live.read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        roll_changelog.roll(live, archive, keep=4)
    assert live.read_bytes() == before


def test_it_refuses_a_table_that_holds_anything_but_rows(tree):
    live, archive, _ = tree
    live.write_text(live.read_text(encoding="utf-8") + "\nstray prose\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not a row"):
        roll_changelog.roll(live, archive, keep=4)


# Since #587 each branch adds its row as docs/planning/changelog.d/<date>_<branch>.md,
# and the roll folds those rows into the table first: unchanged, at their date's place.

def fragments_dir(live: Path) -> Path:
    return live.parent / "changelog.d"


def write_fragment(live: Path, name: str, *rows: str) -> Path:
    path = fragments_dir(live) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(rows), encoding="utf-8")
    return path


def test_fold_moves_fragment_rows_into_the_table_unchanged_and_deletes_them(tree):
    live, _, rows = tree
    newest = "| 2026-09-02 | claude/new | **Newest.** Why, with \\| escaped. |\n"
    middle = "| 2026-08-27 | claude/mid | **Between two days.** Why. |\n"
    a = write_fragment(live, "2026-09-02_claude-new.md", newest)
    b = write_fragment(live, "2026-08-27_claude-mid.md", middle)
    assert roll_changelog.fold(live, fragments_dir(live)) == 2
    folded = table_rows(live)
    assert sorted(folded) == sorted(rows + [newest, middle])
    assert folded[0] == newest
    dates = [r.split("|")[1].strip() for r in folded]
    assert dates == sorted(dates, reverse=True)
    assert not a.exists() and not b.exists()


def test_fold_puts_a_fragment_above_its_own_dates_existing_rows(tree):
    live, _, rows = tree
    same_day = f"| {rows[0].split('|')[1].strip()} | claude/same | **Same day.** Why. |\n"
    write_fragment(live, "2026-08-30_claude-same.md", same_day)
    roll_changelog.fold(live, fragments_dir(live))
    assert table_rows(live)[0] == same_day


def test_fold_with_no_fragments_changes_nothing(tree):
    live, _, _ = tree
    before = live.read_bytes()
    assert roll_changelog.fold(live, fragments_dir(live)) == 0
    assert live.read_bytes() == before


def test_fold_dry_run_writes_nothing(tree):
    live, _, _ = tree
    frag = write_fragment(live, "2026-09-02_claude-new.md", "| 2026-09-02 | claude/new | **N.** W. |\n")
    before = live.read_bytes()
    assert roll_changelog.fold(live, fragments_dir(live), dry_run=True) == 1
    assert live.read_bytes() == before and frag.exists()


@pytest.mark.parametrize("text", ["", "| Date | Branch | Change |\n", "prose\n| 2026-09-02 | b | **x.** y |\n"])
def test_fold_refuses_a_fragment_that_holds_anything_but_rows(tree, text):
    live, _, _ = tree
    write_fragment(live, "2026-09-02_claude-bad.md", text)
    before = live.read_bytes()
    with pytest.raises(SystemExit, match="rows only"):
        roll_changelog.fold(live, fragments_dir(live))
    assert live.read_bytes() == before
