"""The schema-apply action must fail fast on lock contention, not queue.

2026-08-26 22:41 UTC: migration 14's `ALTER TABLE cvm_fi_perfil ADD COLUMN`
(metadata-only, normally instant) hung 4m20s and the server killed the
connection, failing the run and blocking every later migration plus the whole
analytical layer. Four Vercel dashboard builds were mid-flight, and two of
their source queries scan cvm_fi_perfil for 4+ minutes each; the DDL queued
behind their AccessShareLocks waiting for AccessExclusiveLock.

A queued AccessExclusiveLock also blocks every reader that arrives behind it,
so the stuck DDL stalls the very builds it waits on. These tests pin the guard
that makes it give up instead.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ACTION = Path(__file__).resolve().parents[1] / ".github/actions/apply-schema/action.yml"


def _apply_step() -> dict:
    spec = yaml.safe_load(ACTION.read_text())
    steps = spec["runs"]["steps"]
    for step in steps:
        if step.get("name") == "Apply schema + migrations":
            return step
    raise AssertionError(f"no apply step in {ACTION}: {[s.get('name') for s in steps]}")


def test_action_yaml_is_parseable():
    spec = yaml.safe_load(ACTION.read_text())
    assert spec["runs"]["using"] == "composite"
    assert "postgres-url" in spec["inputs"]


def test_apply_sets_a_bounded_lock_timeout():
    body = _apply_step()["run"]
    assert "lock_timeout=" in body, (
        "without lock_timeout a blocked ALTER queues indefinitely and blocks "
        "every reader behind it"
    )
    assert "PGOPTIONS" in body, "the timeout must reach psql, i.e. via PGOPTIONS"


def test_apply_does_not_cap_statement_time():
    # lock_timeout bounds only the wait to ACQUIRE a lock. A statement_timeout
    # would also kill DDL that is legitimately running for a long time (a big
    # index build), which is a different and much worse failure.
    body = _apply_step()["run"]
    assert "statement_timeout=0" in body, (
        "statement_timeout must stay unbounded so a genuinely slow migration "
        "is not aborted mid-flight"
    )


def test_apply_retries_before_failing():
    body = _apply_step()["run"]
    assert "for attempt in 1 2 3" in body, "a lock holder may simply need time"
    assert "sleep" in body


def test_apply_still_stops_on_error_and_covers_schema_and_migrations():
    body = _apply_step()["run"]
    assert "ON_ERROR_STOP=1" in body, "a real SQL error must still fail the job"
    assert "set -euo pipefail" in body
    assert "apply src/store/schema.sql" in body
    assert "src/store/migrations/*.sql" in body


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_apply_body_is_valid_bash():
    body = _apply_step()["run"]
    proc = subprocess.run(
        ["bash", "-n"], input=body, text=True, capture_output=True,
    )
    assert proc.returncode == 0, f"apply step is not valid bash:\n{proc.stderr}"
