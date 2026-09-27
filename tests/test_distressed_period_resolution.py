"""`distressed_securities()` must not default to a bare MAX(period).

Register item 5: a MAX() over a filing date is not a period. Early filers
open the next month days before the rest; on 2026-09-25 fact_security_monthly
held 24 rows at 2026-08 against 3,260 at 2026-07, so the default reported 10
distressed series instead of 173. The default resolves to the newest period
with at least half the previous period's rows.
"""

from __future__ import annotations

import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1]
       / "src/store/analytical/09_analytical_functions.sql").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION {name}(")
    open_tag = SQL.index("$$", start)
    return SQL[open_tag:SQL.index("$$", open_tag + 2)]


def test_default_period_is_not_a_bare_max() -> None:
    body = _function_body("distressed_securities")
    assert not re.search(r"SELECT\s+MAX\(period\)\s+FROM\s+fact_security_monthly", body, re.I)


def test_default_period_requires_a_populated_month() -> None:
    body = _function_body("distressed_securities")
    assert "lag(count(*))" in body
    assert re.search(r"n\s*>=\s*0\.5\s*\*\s*prev_n", body)
