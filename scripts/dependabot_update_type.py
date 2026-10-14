"""Classify a Dependabot PR title as patch, minor, major or unknown.

Used by ``.github/workflows/dependabot_automerge.yml``, which enables
auto-merge only for ``patch`` and ``minor``. Anything this cannot read with
certainty is ``unknown``, and unknown never merges: a grouped update, a SHA
instead of a version, a title Dependabot words differently one day.

    python scripts/dependabot_update_type.py "Bump aiohttp from 3.14.3 to 3.14.4"

A version 0.x counts a minor move as major, as semver says.
"""

from __future__ import annotations

import re
import sys

# "Bump X from A to B" and "Update X requirement from >=A to >=B".
_TITLE = re.compile(r"^(?:Bump|Update) \S+(?: requirement)? from (\S+) to (\S+)$")
_VERSION = re.compile(r"^(?:[<>=!~^]=?)?v?(\d+(?:\.\d+)*)$")


def _parse(token: str) -> tuple[int, ...] | None:
    match = _VERSION.match(token)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def classify(title: str) -> str:
    match = _TITLE.match(title.strip())
    if match is None:
        return "unknown"
    old, new = _parse(match.group(1)), _parse(match.group(2))
    if old is None or new is None or new <= old:
        return "unknown"
    old = old + (0,) * (3 - len(old))
    new = new + (0,) * (3 - len(new))
    if old[0] != new[0]:
        return "major"
    if old[0] == 0 and old[1] != new[1]:
        return "major"
    if old[1] != new[1]:
        return "minor"
    return "patch"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: dependabot_update_type.py <pull request title>")
    print(classify(sys.argv[1]))
