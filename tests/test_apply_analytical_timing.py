"""scripts/apply_analytical.sh prints each file's elapsed seconds and a sorted
summary (#871), without changing what it applies or how it exits.

The script runs against a stand-in `psql` on PATH: every file "succeeds" except
the cron file, which fails mentioning pg_cron (downgraded to a warning), and,
in the failing case, one file that fails outright.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_analytical.sh"
FILES = sorted(p.name for p in (ROOT / "src/store/analytical").glob("[0-9][0-9]_*.sql"))

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(tmp_path: Path, fail_file: str | None = None) -> subprocess.CompletedProcess:
    fail_case = f'*{fail_file}) echo "ERROR: boom"; exit 3;;' if fail_file else ""
    psql = tmp_path / "psql"
    psql.write_text(
        "#!/usr/bin/env bash\n"
        'for a; do case "$a" in\n'
        '  *08_cron_schedules.sql) echo "ERROR: extension pg_cron is not available"; exit 3;;\n'
        f"  {fail_case}\n"
        "esac; done\nexit 0\n",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "POSTGRES_URL": "postgresql://localhost/db"}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True,
                          text=True, timeout=120)


def test_each_file_line_carries_its_elapsed_seconds(tmp_path):
    p = _run(tmp_path)
    assert p.returncode == 0, p.stderr
    for name in FILES:
        if name == "08_cron_schedules.sql":
            assert re.search(rf"^  warn {re.escape(name)}  \(\d+\.\ds\) — pg_cron", p.stdout, re.M)
        else:
            assert re.search(rf"^  ok   {re.escape(name)}  \(\d+\.\ds\)$", p.stdout, re.M), name


def test_summary_lists_every_file_slowest_first_then_total(tmp_path):
    p = _run(tmp_path)
    summary = p.stdout.split("Timing, slowest first:\n", 1)[1].split("\n\n", 1)[0]
    rows = [re.fullmatch(r"\s+(\d+)\.(\d)s  (\S+)", line) for line in summary.splitlines()]
    assert all(rows), summary
    names = [m.group(3) for m in rows]
    assert names[-1] == "total"
    assert sorted(names[:-1]) == FILES
    tenths = [int(m.group(1)) * 10 + int(m.group(2)) for m in rows[:-1]]
    assert tenths == sorted(tenths, reverse=True)
    assert "Applied: " in p.stdout.split(summary, 1)[1]


def test_a_failure_still_exits_nonzero_and_is_timed(tmp_path):
    bad = next(n for n in FILES if n != "08_cron_schedules.sql")
    p = _run(tmp_path, fail_file=bad)
    assert p.returncode == 1
    assert re.search(rf"^  FAIL {re.escape(bad)}  \(\d+\.\ds\)$", p.stdout, re.M)
    assert f"Analytical layer apply FAILED for: {bad}" in p.stderr
