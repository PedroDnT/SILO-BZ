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


def test_apply_retries_only_on_lock_timeout():
    """Backfill #18 retried `column "tp_fundo" does not exist` three times.

    The sleep loop is for AccessExclusiveLock waiters. A deterministic SQL
    error must fail on the first attempt with the real message, not a
    lock-contention annotation.
    """
    body = _apply_step()["run"]
    assert "canceling statement due to lock timeout" in body
    assert "Not retrying" in body
    assert body.index("canceling statement due to lock timeout") < body.index(
        "retrying in"
    )


def test_apply_still_stops_on_error_and_covers_schema_and_migrations():
    body = _apply_step()["run"]
    assert "ON_ERROR_STOP=1" in body, "a real SQL error must still fail the job"
    assert "set -euo pipefail" in body
    assert "apply src/store/schema.sql" in body
    assert "src/store/migrations/*.sql" in body


def test_apply_catalog_guards_noop_add_column():
    # ADD COLUMN IF NOT EXISTS still takes AccessExclusiveLock before checking
    # the catalog (Daily CVM Ingest #167 / schema.sql:268). The rewrite must
    # happen on every file, including historical migrations we do not edit.
    body = _apply_step()["run"]
    assert "scripts/guard_noop_ddl.py" in body
    assert "python3 scripts/guard_noop_ddl.py" in body
    assert "-f \"$guarded\"" in body or '-f "$guarded"' in body
    assert "-f \"$file\"" not in body, (
        "psql must apply the catalog-guarded rewrite, not the raw file"
    )
    # CREATE MATERIALIZED VIEW ... AS SELECT holds pg_type for the scan
    # (Daily CVM Ingest #184). The rewriter must run on every file so
    # historical migration 27 (WITH DATA) is rewritten at apply time.
    assert "WITH NO DATA" in body or "guard_noop_ddl.py" in body


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_apply_body_is_valid_bash():
    body = _apply_step()["run"]
    proc = subprocess.run(
        ["bash", "-n"], input=body, text=True, capture_output=True,
    )
    assert proc.returncode == 0, f"apply step is not valid bash:\n{proc.stderr}"


def test_apply_does_not_drop_etf_views_before_schema():
    """Unconditional DROP VIEW before apply left etf_daily missing on #18.

    Migration 01 already drops the views when it actually retypes
    cvm_fi_diario; 06/10 recreate them. A pre-flight DROP is
    AccessExclusiveLock on every ingest and is not rolled back if
    schema.sql then fails.
    """
    spec = yaml.safe_load(ACTION.read_text())
    names = [s.get("name", "") for s in spec["runs"]["steps"]]
    assert not any("drop" in n.lower() and "view" in n.lower() for n in names)
    assert "DROP VIEW" not in _apply_step()["run"]
