"""backfill.yml can force a re-ingest of years coverage calls complete.

Coverage counts what landed, not whether it landed at the right grain. After
migration 49 widened cvm_fi_cda's key, every 2005-2022 year of block 1 was
"complete" (a yearly HIST row logged ok) and still held one bond per fund, and
the gate skipped them, so the only fix could not be applied. fi_force bypasses
the gate for ONE doc type.
"""

import importlib.util
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

BACKFILL = Path(__file__).resolve().parents[1] / ".github/workflows/backfill.yml"


def _inputs():
    wf = yaml.safe_load(BACKFILL.read_text())
    on = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    return on["workflow_dispatch"]["inputs"]


def test_fi_force_is_a_boolean_input_defaulting_off():
    force = _inputs()["fi_force"]
    assert force["type"] == "boolean"
    assert force["default"] is False


def _gate():
    path = BACKFILL.parents[2] / "scripts/backfill_fi_year_gate.py"
    spec = importlib.util.spec_from_file_location("backfill_fi_year_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_force_runs_before_any_skip_and_only_for_one_doc_type():
    gate = _gate()
    complete = {
        "counts": {d: 12 for d in gate.MONTHLY_DOC_TYPES},
        "yearly_status": "ok",
        "diario_rows": 3_000_000,
    }
    skip, msg = gate.decide(
        2010, "cda", repair_gaps=False, months="", force=True, coverage=complete
    )
    assert not skip and "forced" in msg, "a SKIP branch runs before the force check"
    # Force never widens to all of FI: a complete year still skips.
    skip, _ = gate.decide(
        2024, "all", repair_gaps=False, months="", force=True, coverage=complete
    )
    assert skip
