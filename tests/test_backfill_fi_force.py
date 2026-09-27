"""backfill.yml can force a re-ingest of years coverage calls complete.

Coverage counts what landed, not whether it landed at the right grain. After
migration 49 widened cvm_fi_cda's key, every 2005-2022 year of block 1 was
"complete" (a yearly HIST row logged ok) and still held one bond per fund, and
the gate skipped them, so the only fix could not be applied. fi_force bypasses
the gate for ONE doc type.
"""

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


def test_force_runs_before_any_skip_and_only_for_one_doc_type():
    body = BACKFILL.read_text()
    gate = body[body.index('skip = False\n          requested_doc = "${{ inputs.fi_doc_type }}"'):]
    force = gate.index('"${{ inputs.fi_force }}" == "true" and requested_doc != "all"')
    first_skip = gate.index("skip = True")
    assert force < first_skip, "a SKIP branch runs before the force check"
