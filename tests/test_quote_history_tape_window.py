"""The start of the tape (#417): what has to agree with it, and where it is published.

The window refusal itself belongs to the research price contract (catalog v48):
`api.quote_history` raises 22023 `reason=outside_coverage` for a window that starts
before the instrument's first session or holds none of its sessions, and
tests/test_quote_history_contract.py and tests/sql/quote_history_behaviour.sql pin
and execute it. It reads the first session off the tape rather than from a literal,
so the thing that can still drift is the set of literals around it. This file pins
those to one date, and pins where a caller is told the date.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "src/store/analytical/19_api_contract.sql"
RESEARCH = ROOT / "src/store/analytical/28_api_research.sql"
INDEX = ROOT / "src/store/analytical/29_api_index.sql"
CASH_MV = ROOT / "src/store/migrations/56_mv_b3_cash_event.sql"

START = "2019-01-02"


def _code(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _function() -> str:
    sql = _code(CONTRACT.read_text(encoding="utf-8"))
    start = sql.index("CREATE OR REPLACE FUNCTION api.quote_history(")
    return sql[start:sql.index("$$;", start) + 3]


def test_one_date_floors_the_tape_the_sweep_the_cash_events_and_the_universe():
    """The adjusted and total-return closes are only built from this date, so the
    literals that floor them must not drift apart."""
    from src.pipeline.b3_pipeline import TAPE_START

    assert TAPE_START.isoformat() == START
    assert f"DATE '{START}'" in _code(RESEARCH.read_text(encoding="utf-8"))
    # the history filter and the supplement filter, one each
    assert _code(CASH_MV.read_text(encoding="utf-8")).count(f"DATE '{START}'") == 2


def test_the_window_refusal_reads_the_start_of_the_tape_from_the_data():
    body = _function()
    assert "v_from < v_cov_start" in body
    assert "reason=outside_coverage" in body
    # Named in the message when the instrument's coverage begins on it ...
    assert "' (the tape starts ' || v_tape_start || ')'" in body
    # ... and taken from the tape, so there is no second literal to drift.
    assert re.search(r"SELECT min\(b\.trade_date\) INTO v_tape_start\s+FROM public\.b3_cotahist b WHERE b\.tpmerc = '010'", body)
    assert f"DATE '{START}'" not in body


def test_coverage_publishes_the_tape_start_on_the_quotes_row():
    sql = CONTRACT.read_text(encoding="utf-8")
    arm = sql[sql.index("SELECT 'quotes'::text AS dataset"):]
    arm = arm[:arm.index("'b3'::text AS log_entity")]
    assert "B3 COTAHIST cash tape from" in arm and "MIN(q.trade_date)" in arm
    assert "refuses a window that starts before an instrument" in arm
    assert "NULL::text AS notes" not in arm


def test_the_catalog_says_where_the_tape_starts_and_that_the_index_goes_further_back():
    from serve.catalog import catalog_payload

    text = " ".join(catalog_payload()["constraints"])
    assert f"the tape starts {START}, see coverage()" in text
    assert "IBOV from 1968-01-02" in text


def test_the_index_is_not_bound_by_the_tape_window():
    sql = _code(INDEX.read_text(encoding="utf-8"))
    assert START not in sql
    assert "outside_coverage" not in sql
