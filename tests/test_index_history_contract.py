"""B3 index closing levels: the fetcher's checks and api.index_history (#412, #415).

The fixture is B3's real 2025 answer for IBOV (fetched 2026-09-30). It carries
B3's own published year-end close, 161.125,37 on 2025-12-30, and 250 sessions,
the same count the COTAHIST tape holds for 2025. What the SQL does on rows is
executed in CI by tests/sql/index_history_behaviour.sql.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.fetchers.b3_index_level_fetcher import B3IndexLevelError, parse_level, parse_year

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/b3_index_level_ibov_2025.json"
SQL28 = (ROOT / "src/store/analytical/28_api_research.sql").read_text(encoding="utf-8")
TODAY = date(2026, 9, 30)


def _body():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rows():
    return parse_year(_body(), "IBOV", 2025, today=TODAY)


def test_the_published_year_end_close_is_read_exactly():
    rows = _rows()
    close = {r["trade_date"]: r["level"] for r in rows}
    assert close["2025-12-30"] == Decimal("161125.37")
    assert len(rows) == 250
    assert rows[0]["trade_date"] == "2025-01-02" and rows[-1]["trade_date"] == "2025-12-30"
    assert all(r["index_code"] == "IBOV" and r["source"] == "b3_index_statistics" for r in rows)
    assert len({r["trade_date"] for r in rows}) == len(rows), "one row per session"


def test_levels_parse_only_in_the_published_format():
    assert parse_level("161.125,37") == Decimal("161125.37")
    assert parse_level("999,99") == Decimal("999.99")
    for bad in ("161125.37", "161.125,3", "161,125.37", "", None, "abc"):
        with pytest.raises(B3IndexLevelError):
            parse_level(bad)


def test_a_null_grid_is_an_error_not_an_empty_year():
    """An unknown code answers HTTP 200 with results null (IFNM, 2026-09-29)."""
    for body in ({"results": None}, {"results": []}, {}, None):
        with pytest.raises(B3IndexLevelError):
            parse_year(body, "IBOV", 2025, today=TODAY)


def test_a_level_on_a_weekend_or_in_the_future_raises():
    body = _body()
    # 2025-01-04 was a Saturday.
    next(r for r in body["results"] if r["day"] == 4)["rateValue1"] = "120.000,00"
    with pytest.raises(B3IndexLevelError, match="weekend"):
        parse_year(body, "IBOV", 2025, today=TODAY)
    with pytest.raises(B3IndexLevelError, match="future"):
        parse_year(_body(), "IBOV", 2025, today=date(2025, 6, 1))


def test_an_impossible_date_or_a_repeated_day_raises():
    body = _body()
    next(r for r in body["results"] if r["day"] == 30)["rateValue2"] = "120.000,00"
    with pytest.raises(B3IndexLevelError, match="impossible"):
        parse_year(body, "IBOV", 2025, today=TODAY)
    body = _body()
    body["results"].append(copy.deepcopy(body["results"][0]))
    with pytest.raises(B3IndexLevelError, match="repeated"):
        parse_year(body, "IBOV", 2025, today=TODAY)


def test_the_published_monthly_extremes_must_match_the_grid():
    body = _body()
    body["max"]["rateValue12"] = "1,00"
    with pytest.raises(B3IndexLevelError, match="max"):
        parse_year(body, "IBOV", 2025, today=TODAY)


def test_a_past_year_with_no_level_raises():
    body = {"results": [{"day": d, **{f"rateValue{m}": None for m in range(1, 13)}} for d in range(1, 32)]}
    with pytest.raises(B3IndexLevelError, match="no level"):
        parse_year(body, "IBOV", 2025, today=TODAY)
    # The current year may be empty in its first days.
    assert parse_year(body, "IBOV", 2026, today=date(2026, 1, 2)) == []


def _function() -> str:
    sql = re.sub(r"--[^\n]*", "", SQL28)
    start = sql.index("CREATE OR REPLACE FUNCTION api.index_history(")
    return sql[start:sql.index("$$;", sql.index("AS $$", start) + 5)]


def test_the_sql_code_list_is_the_pipelines():
    from src.pipeline.b3_pipeline import INDEX_LEVEL_CODES

    m = re.search(r"v_codes\s+TEXT\[\]\s*:=\s*ARRAY\[(.*?)\]", _function())
    assert m
    assert tuple(x.strip().strip("'") for x in m.group(1).split(",")) == INDEX_LEVEL_CODES


def test_tickers_are_refused_by_construction():
    body = _function()
    assert "NOT v_code = ANY (v_codes)" in body
    assert "reason=unknown_index" in body
    assert "BOVA11" in body and "IBOV11" in body
    # It reads only the published levels, never the tape.
    assert "b3_cotahist" not in body
    assert "FROM public.b3_index_level" in body


def test_it_pages_refuses_over_the_cap_and_outside_the_coverage():
    body = _function()
    assert "api.parse_date_cursor(p_after, 'index_history')" in body
    assert "api.assert_row_cap((SELECT count(*) FROM page), v_paging, 'index_history')" in body
    assert "LIMIT 1001" in body
    assert body.count("reason=outside_coverage") == 2
    assert "SECURITY DEFINER" in body and "SET search_path = ''" in body


def test_the_behaviour_file_runs_in_ci():
    wf = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "tests/sql/index_history_behaviour.sql" in wf
