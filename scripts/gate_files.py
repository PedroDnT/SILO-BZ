"""Say which changed paths are gate files.

A gate file is one that decides what an agent may do or what a pull request
must pass: the workflows, the agent settings and prompts, the rule files and
the pipeline verifier. A pull request that changes one is merged by the owner,
never by auto-merge. ``.github/workflows/gate_files.yml`` runs this on every
pull request and fails while such a pull request has auto-merge on.

The gate list lives here and nowhere else.

    git diff --name-only origin/main... | python scripts/gate_files.py

Paths come on stdin, one per line, or as arguments. The matches are printed
one per line, in the order given, each once.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

# Everything under these directories. The trailing slash matters: ".githubx/"
# is not a gate path.
GATE_DIRS: tuple[str, ...] = (".github/", ".claude/")

# These files exactly, from the repository root. "AGENTS.md" is the root file
# only; "docs/planning/AGENTS.md" is listed on its own.
GATE_FILES: tuple[str, ...] = (
    "CLAUDE.md",
    "AGENTS.md",
    "docs/planning/AGENTS.md",
    "scripts/verify_pipeline.py",
)


def is_gate_path(path: str) -> bool:
    return path in GATE_FILES or path.startswith(GATE_DIRS)


def gate_paths(paths: Iterable[str]) -> list[str]:
    """Return the gate paths among ``paths``, in order, without repeats."""
    seen: dict[str, None] = {}
    for raw in paths:
        path = raw.strip()
        if path and is_gate_path(path):
            seen.setdefault(path)
    return list(seen)


if __name__ == "__main__":
    for match in gate_paths(sys.argv[1:] or sys.stdin):
        print(match)
