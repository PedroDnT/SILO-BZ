"""Pins research_build.yml, the workflow that builds the DUSTIN-BR matrix.

It connects with the POSTGRES_URL secret, the same one the ingest writes
with, so the rules that keep it harmless are asserted here rather than
trusted to review:

* manual dispatch only;
* outside the ``supabase-ingest`` writer group: it writes nothing (its queries
  run read only, see ``test_every_warehouse_query_runs_read_only``), and
  joining the group would let a dispatch cancel a pending ingest, since
  GitHub keeps one pending run per group;
* it runs the builder's quality entry point and nothing that writes;
* the files are uploaded even when the look-ahead check fails the run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/research_build.yml"


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list:
    return _spec()["jobs"]["build"]["steps"]


def test_dispatch_only():
    triggers = _spec().get(True) or _spec().get("on")  # PyYAML reads `on:` as True
    assert set(triggers) == {"workflow_dispatch"}


def test_never_joins_the_writer_group():
    spec = _spec()
    groups = [spec.get("concurrency"), spec["jobs"]["build"].get("concurrency")]
    assert "supabase-ingest" not in yaml.safe_dump(groups)
    assert spec["permissions"] == {"contents": "read"}


def test_runs_the_quality_build_and_nothing_that_writes():
    runs = "\n".join(s.get("run", "") for s in _steps())
    assert "python -m research_examples.dustin_br.quality" in runs
    assert "python -m research_examples.dustin_br.model --matrix out/dustin_br.csv" in runs
    for forbidden in ("apply_schema", "apply-schema", "apply_analytical", "run_daily", "run_backfill",
                      "market_pipeline", "psql"):
        assert forbidden not in runs, forbidden
    assert not any("apply-schema" in s.get("uses", "") for s in _steps())


def test_the_files_are_uploaded_even_when_the_check_fails():
    upload = next(s for s in _steps() if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"]["path"] == "out/"
