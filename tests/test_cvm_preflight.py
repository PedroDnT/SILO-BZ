"""The CVM preflight: ask once, cheaply, before spending a whole dispatch.

A backfill dispatch is up to 300 minutes and every download goes to one host.
When CVM refuses this runner's IP the entire run is doomed before it starts,
and without a preflight the only way to learn that is the full grind. Measured
2026-08-29: the 06:00 ingest spent ~40 minutes proving the same refusal across
twenty slices, then the 07:35 health check reported the pipeline red for it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_cvm_reachable.py"
BACKFILL = ROOT / ".github/workflows/backfill.yml"
DAILY = ROOT / ".github/workflows/daily_ingest.yml"
WATCHDOG = ROOT / ".github/workflows/watchdog.yml"

yaml = pytest.importorskip("yaml")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
    )


class TestClassification:
    """What counts as 'unreachable' is the whole subtlety here."""

    def test_unresolvable_host_is_unreachable(self):
        r = _run("--url", "https://cvm-does-not-resolve.invalid/x.zip",
                 "--attempts", "1", "--timeout", "5")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "UNREACHABLE" in r.stderr

    def test_it_names_the_recovery(self):
        """A red preflight must say what to do, not just that it is red."""
        r = _run("--url", "https://cvm-does-not-resolve.invalid/x.zip",
                 "--attempts", "1", "--timeout", "5")
        assert "fresh runner IP" in r.stderr


class TestWiring:
    def test_every_cvm_job_gates_on_the_preflight(self):
        """Otherwise the check exists but nothing waits for its answer."""
        jobs = yaml.safe_load(BACKFILL.read_text())["jobs"]
        assert "cvm-preflight" in jobs
        for name in ("backfill-fi", "backfill-other", "backfill-etf"):
            assert "cvm-preflight" in jobs[name]["needs"], (
                f"{name} downloads from CVM but does not gate on the preflight"
            )

    def test_bacen_does_not_gate_on_it(self):
        """BACEN never touches CVM; blocking it on CVM would invent an outage."""
        jobs = yaml.safe_load(BACKFILL.read_text())["jobs"]
        needs = jobs["backfill-bacen"].get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert "cvm-preflight" not in needs

    def test_preflight_is_skipped_for_bacen_only_runs(self):
        jobs = yaml.safe_load(BACKFILL.read_text())["jobs"]
        assert "bacen_only" in jobs["cvm-preflight"]["if"]

    def test_preflight_uses_only_the_standard_library(self):
        """It must not be the step that dies on a dependency while reporting
        that the network is fine."""
        src = SCRIPT.read_text()
        for third_party in ("import requests", "import aiohttp", "import httpx"):
            assert third_party not in src

    def test_daily_ingest_probes_before_run_daily(self):
        """Run 33237536770 wrote 44 unhealed errors because daily never asked."""
        text = DAILY.read_text()
        spec = yaml.safe_load(text)
        names = [s.get("name") for s in spec["jobs"]["ingest"]["steps"]]
        assert "Probe dados.cvm.gov.br" in names
        assert names.index("Probe dados.cvm.gov.br") < names.index("Run daily update")
        assert "python scripts/check_cvm_reachable.py" in text
        # analytics-only / b3-backfill must not be blocked on CVM.
        probe = next(
            s for s in spec["jobs"]["ingest"]["steps"]
            if s.get("name") == "Probe dados.cvm.gov.br"
        )
        condition = str(probe.get("if", ""))
        assert "mode == 'daily'" in condition
        assert "schedule" in condition

    def test_watchdog_probes_before_recovery_ingest(self):
        text = WATCHDOG.read_text()
        spec = yaml.safe_load(text)
        names = [s.get("name") for s in spec["jobs"]["watchdog"]["steps"]]
        assert "Probe dados.cvm.gov.br" in names
        assert names.index("Probe dados.cvm.gov.br") < names.index(
            "Run daily ingest (recovery)"
        )
        assert "python scripts/check_cvm_reachable.py" in text
