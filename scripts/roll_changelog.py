#!/usr/bin/env python3
"""Roll the oldest rows of docs/planning/CHANGELOG.md into a frozen archive file.

The live changelog keeps the newest KEEP rows. Everything older moves, byte for
byte and in the same order, into docs/archive/changelog/<oldest>_to_<newest>.md.
The push hook and test.yml read the live file and the archive files together, so
a roll is never a dropped row; deleting or rewording a row still is.

Run it by hand when the live file has grown (about once a month):

    python scripts/roll_changelog.py            # keep the newest 60 rows
    python scripts/roll_changelog.py --dry-run  # say what it would do

It refuses, rather than guesses, when the table holds anything but rows, or when
the archive file it would write already exists.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "docs/planning/CHANGELOG.md"
ARCHIVE = ROOT / "docs/archive/changelog"
KEEP = 60

TABLE_HEADER = "| Date | Branch | Change |\n| --- | --- | --- |\n"
POINTER = "Older rows are in [docs/archive/changelog/](../archive/changelog/), frozen.\n"


def _date(row: str) -> str:
    return row.split("|")[1].strip()


def roll(changelog: Path, archive: Path, keep: int = KEEP, dry_run: bool = False) -> Path | None:
    """Move rows beyond the newest `keep`; return the archive file, or None."""
    lines = changelog.read_text(encoding="utf-8").splitlines(keepends=True)
    rule = next((i for i, line in enumerate(lines) if line.startswith("| --- |")), None)
    if rule is None:
        raise SystemExit(f"{changelog}: no table header rule; refusing to guess")
    head, body = lines[: rule + 1], lines[rule + 1:]
    stray = [line for line in body if not line.startswith("| 20")]
    if stray:
        raise SystemExit(f"{changelog}: the table holds a line that is not a row; refusing to guess: {stray[0][:80]!r}")
    if len(body) <= keep:
        print(f"{len(body)} rows, at most {keep}: nothing to roll")
        return None

    kept, rolled = body[:keep], body[keep:]
    target = archive / f"{_date(rolled[-1])}_to_{_date(rolled[0])}.md"
    if target.exists():
        raise SystemExit(f"{target} already exists; archive files are frozen, never overwritten")
    print(f"rolling {len(rolled)} rows ({_date(rolled[-1])} to {_date(rolled[0])}) into {target.name}; keeping {len(kept)}")
    if dry_run:
        return None

    if POINTER not in head:
        head.insert(next((i for i, line in enumerate(head) if line.startswith("| Date")), len(head)), POINTER + "\n")
    text = (f"# Changelog archive, {_date(rolled[-1])} to {_date(rolled[0])}\n\n"
            "Rows rolled out of [planning/CHANGELOG.md](../../planning/CHANGELOG.md), "
            "unchanged and newest first. Frozen: do not edit.\n\n" + TABLE_HEADER + "".join(rolled))
    archive.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    changelog.write_text("".join(head + kept), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--keep", type=int, default=KEEP, help=f"rows to keep (default {KEEP})")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    roll(CHANGELOG, ARCHIVE, args.keep, args.dry_run)


if __name__ == "__main__":
    main()
