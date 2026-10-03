"""Offline tests for B3's index levels (#412): fetch, parse, divisor steps, ingest.

The fixtures are verbatim answers from B3's index statistics proxy, captured
2026-09-30: IBOV 2025 (the year the ticket pins, 2025-12-30 = 161,125.37),
IBOV 1997 (the divisor step of 1997-03-03) and IFNM 2025, a code the endpoint
does not publish (HTTP 200 with results=null).
"""

from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.b3_index_fetcher import B3IndexFetcher, B3IndexNoResults
from src.pipeline import ingest_b3_index as idx
from src.pipeline.b3_pipeline import B3Ingestor

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "b3_index"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _grid(levels: dict[date, str]) -> dict:
    """A year grid as B3 serves it, from {session: "1.234,56"}."""
    results = [{"day": d, **{f"rateValue{m}": None for m in range(1, 13)}} for d in range(1, 32)]
    for session, cell in levels.items():
        results[session.day - 1][f"rateValue{session.month}"] = cell
    return {"min": {"day": 0}, "max": {"day": 0}, "results": results}


class _Response:
    def __init__(self, text: str, status: int = 200):
        self.text, self.status_code = text, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------- transport


def test_the_token_carries_index_language_and_year():
    token = B3IndexFetcher._token("IBOV", 2025)
    assert json.loads(base64.b64decode(token)) == {
        "index": "IBOV", "language": "pt-br", "year": "2025",
    }


def test_a_null_result_that_never_clears_raises_after_bounded_attempts():
    """IFNM answers 200 with results=null on every try. For a configured index
    that is an error, never an empty year: the retry is bounded and then raises."""
    fetcher = B3IndexFetcher(max_retries=3, sleep_between=0)
    body = (FIXTURES / "IFNM_2025_null.json").read_text()
    with patch.object(fetcher.session, "get", return_value=_Response(body)) as get:
        with pytest.raises(B3IndexNoResults, match="all 3 attempts"):
            fetcher.fetch_year("IFNM", 2025)
    assert get.call_count == 3


def test_a_null_once_then_data_succeeds():
    """UTIL 2012 answered null once and data on every later fetch (2026-10-03)."""
    fetcher = B3IndexFetcher(max_retries=3, sleep_between=0)
    null = (FIXTURES / "IFNM_2025_null.json").read_text()
    good = (FIXTURES / "IBOV_2025.json").read_text()
    with patch.object(
        fetcher.session, "get", side_effect=[_Response(null), _Response(good)]
    ) as get:
        payload = fetcher.fetch_year("UTIL", 2012)
    assert payload["results"]
    assert get.call_count == 2


def test_two_nulls_then_data_still_succeeds_and_the_pause_backs_off():
    fetcher = B3IndexFetcher(max_retries=3, sleep_between=0.5)
    null = (FIXTURES / "IFNM_2025_null.json").read_text()
    good = (FIXTURES / "IBOV_2025.json").read_text()
    with patch.object(
        fetcher.session, "get",
        side_effect=[_Response(null), _Response(null), _Response(good)],
    ) as get, patch("src.fetchers.b3_index_fetcher.time.sleep") as sleep:
        assert fetcher.fetch_year("UTIL", 2012)["results"]
    assert get.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]


def test_a_null_then_a_transport_failure_raises_the_last_error_not_an_empty_year():
    fetcher = B3IndexFetcher(max_retries=2, sleep_between=0)
    null = (FIXTURES / "IFNM_2025_null.json").read_text()
    with patch.object(
        fetcher.session, "get", side_effect=[_Response(null), RuntimeError("SSL EOF")]
    ):
        with pytest.raises(RuntimeError, match="failed after 2 attempts"):
            fetcher.fetch_year("UTIL", 2012)


def test_a_transient_failure_is_retried_and_a_persistent_one_raises():
    fetcher = B3IndexFetcher(max_retries=3, sleep_between=0)
    good = (FIXTURES / "IBOV_2025.json").read_text()
    with patch.object(
        fetcher.session, "get", side_effect=[RuntimeError("SSL EOF"), _Response(good)]
    ) as get:
        assert fetcher.fetch_year("IBOV", 2025)["results"]
    assert get.call_count == 2
    with patch.object(fetcher.session, "get", return_value=_Response("", 200)):
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            fetcher.fetch_year("IBOV", 2025)


# -------------------------------------------------------------------- parse


def test_ibov_2025_year_end_is_b3s_published_close():
    records = idx.parse_year("IBOV", 2025, _fixture("IBOV_2025.json"))
    by_date = {r["trade_date"]: r for r in records}
    assert by_date[date(2025, 12, 30)]["level"] == Decimal("161125.37")
    assert all(r["index_code"] == "IBOV" and r["level"] > 0 for r in records)
    assert all(r["trade_date"].weekday() < 5 for r in records)
    assert len({r["trade_date"] for r in records}) == len(records)
    # A year of sessions, not a grid of 372 cells.
    assert 240 <= len(records) <= 252


def test_null_cells_are_days_without_a_session_not_errors():
    records = idx.parse_year("IBOV", 2025, _grid({date(2025, 1, 2): "120.000,00"}))
    assert [r["trade_date"] for r in records] == [date(2025, 1, 2)]


def test_a_value_on_a_date_that_does_not_exist_raises():
    grid = _grid({})
    grid["results"][29]["rateValue2"] = "100,00"  # 30 February
    with pytest.raises(ValueError, match="non-existent date"):
        idx.parse_year("IBOV", 2025, grid)


@pytest.mark.parametrize("cell", ["n/d", "0,00", "-5,00"])
def test_a_cell_that_is_not_a_positive_level_raises_never_coerced(cell):
    with pytest.raises(ValueError, match="not a positive level"):
        idx.parse_year("IBOV", 2025, _grid({date(2025, 1, 2): cell}))


def test_a_null_result_payload_raises_in_the_parser_too():
    with pytest.raises(ValueError, match="results is null"):
        idx.parse_year("IBOV", 2025, _fixture("IFNM_2025_null.json"))


# ------------------------------------------------------------ divisor steps


def test_the_divisor_step_list_is_the_eleven_found_in_the_series():
    steps = idx.INDEX_DIVISOR_STEPS["IBOV"]
    assert len(steps) == 11, "a step dropped from the list would be served as a return"
    assert steps[date(1983, 10, 4)] == 100
    assert all(d == 10 for k, d in steps.items() if k != date(1983, 10, 4))
    assert max(steps) == date(1997, 3, 3), "no step since 1997"
    assert date(1991, 2, 4) not in steps, "+36% on 1991-02-04 is a real move"


def test_1997_marks_the_first_session_on_the_new_scale_and_not_the_one_before():
    records = idx.parse_year("IBOV", 1997, _fixture("IBOV_1997.json"))
    idx.mark_divisor_steps("IBOV", records)
    flagged = [r["trade_date"] for r in records if r["divisor_step"]]
    assert flagged == [date(1997, 3, 3)]
    by_date = {r["trade_date"]: r for r in records}
    assert by_date[date(1997, 2, 28)]["level"] == Decimal("88287.30")
    assert by_date[date(1997, 3, 3)]["level"] == Decimal("8978.22")
    assert not by_date[date(1997, 2, 28)]["divisor_step"]


def _series(*pairs: tuple[date, str]) -> list[dict]:
    return [
        {"index_code": "IBOV", "trade_date": d, "level": Decimal(v), "divisor_step": False,
         "source": idx.SOURCE}
        for d, v in pairs
    ]


def test_an_unlisted_one_session_drop_is_refused_not_served_as_a_return():
    records = _series((date(2020, 3, 11), "100000"), (date(2020, 3, 12), "30000"))
    with pytest.raises(ValueError, match="not a listed divisor step"):
        idx.mark_divisor_steps("IBOV", records)


def test_an_unlisted_one_session_jump_up_is_refused_too():
    records = _series((date(2020, 3, 11), "50000"), (date(2020, 3, 12), "120000"))
    with pytest.raises(ValueError, match="not a listed divisor step"):
        idx.mark_divisor_steps("IBOV", records)


def test_a_large_real_move_inside_the_bound_is_not_a_step():
    """+36% (1991-02-04) and +33% (1999-01-15) are real and stay unflagged."""
    records = _series((date(1999, 1, 14), "5000"), (date(1999, 1, 15), "6670"))
    idx.mark_divisor_steps("IBOV", records)
    assert not any(r["divisor_step"] for r in records)


def test_a_listed_step_with_the_wrong_ratio_is_refused():
    records = _series((date(1997, 2, 28), "88287.30"), (date(1997, 3, 3), "88000.00"))
    with pytest.raises(ValueError, match="listed as a divisor-10 step"):
        idx.mark_divisor_steps("IBOV", records)


def test_a_listed_step_inside_the_span_with_no_session_is_refused():
    records = _series((date(1997, 2, 28), "88287.30"), (date(1997, 3, 4), "8961.44"))
    with pytest.raises(ValueError, match="has no published session"):
        idx.mark_divisor_steps("IBOV", records)


def test_steps_outside_the_ingested_span_are_not_required():
    records = _series((date(2025, 12, 29), "160000"), (date(2025, 12, 30), "161125.37"))
    idx.mark_divisor_steps("IBOV", records)
    assert not any(r["divisor_step"] for r in records)


# -------------------------------------------------------------- the pipeline


@pytest.mark.parametrize(
    "year, today, expected",
    [
        (2027, date(2027, 1, 3), True),
        (2027, date(2027, 1, 10), True),
        (2027, date(2027, 1, 11), False),
        (2026, date(2027, 1, 3), False),
        (2027, date(2027, 6, 1), False),
    ],
)
def test_only_the_current_year_in_early_january_may_be_empty(year, today, expected):
    assert idx.year_may_be_empty(year, today) is expected


@pytest.fixture(autouse=True)
def _audit(audit_log):
    """Every ingest here writes its audit row through the capture, never a database."""
    return audit_log


def _ingestor() -> B3Ingestor:
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()):
        return B3Ingestor(fetcher=MagicMock())


def _fetcher_serving(payloads: dict[int, object]) -> MagicMock:
    fetcher = MagicMock()
    fetcher.sleep_between = 0

    def fetch_year(code, year):
        value = payloads[year]
        if isinstance(value, Exception):
            raise value
        return value

    fetcher.fetch_year.side_effect = fetch_year
    return fetcher


@pytest.mark.asyncio
async def test_every_year_is_fetched_and_one_log_row_is_written(monkeypatch, audit_log):
    monkeypatch.setitem(idx.FIRST_YEAR, "IBOV", 2024)
    payloads = {
        2024: _grid({date(2024, 12, 30): "120.000,00"}),
        2025: _grid({date(2025, 12, 30): "161.125,37"}),
    }
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher",
               return_value=_fetcher_serving(payloads)) as cls, \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels", return_value=2) as up:
        n = await ing.ingest_index_levels(("IBOV",), today=date(2025, 12, 31))
    assert n == 2
    assert [c.args[1] for c in cls.return_value.fetch_year.call_args_list] == [2024, 2025]
    written = up.call_args.args[1]
    assert [r["trade_date"] for r in written] == [date(2024, 12, 30), date(2025, 12, 30)]
    assert [r["doc_type"] for r in audit_log.started] == ["index_levels"]
    (row,) = audit_log.finished
    assert (row["status"], row["rows"], row["error"]) == ("ok", 2, None)


def test_the_configured_indices_are_the_verified_eight_plus_ibov_and_never_ieex():
    """#416: IBOV and the eight verified codes, each with its own first year.
    IEEX stays out (unexplained +70% / -29% in 1999-03)."""
    assert idx.INDEX_CODES == (
        "IBOV", "IBXX", "IBXL", "IFIX", "SMLL", "IDIV", "ICON", "IMOB", "UTIL",
    )
    assert "IEEX" not in idx.INDEX_CODES and "IEEX" not in idx.FIRST_YEAR
    assert idx.FIRST_YEAR == {
        "IBOV": 1968, "IBXX": 1994, "IBXL": 1997, "IFIX": 2010, "SMLL": 2005,
        "IDIV": 2005, "ICON": 2006, "IMOB": 2007, "UTIL": 2005,
    }
    assert set(idx.FIRST_YEAR) == set(idx.INDEX_CODES)
    assert len(set(idx.INDEX_CODES)) == len(idx.INDEX_CODES)


@pytest.mark.asyncio
async def test_each_configured_index_is_fetched_from_its_own_first_year(monkeypatch):
    """The depth of an index is its own history, not IBOV's 1968."""
    monkeypatch.setattr(idx, "INDEX_DIVISOR_STEPS", {})  # one stub session a year
    fetcher = MagicMock()
    fetcher.sleep_between = 0
    seen: dict[str, list[int]] = {}

    def fetch_year(code, year):
        seen.setdefault(code, []).append(year)
        # one session per year, level 1,000 on the first and rising after
        return _grid({date(year, 6, 1): "1.000,00"})

    fetcher.fetch_year.side_effect = fetch_year
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher", return_value=fetcher), \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels", return_value=0) as up:
        await ing.ingest_index_levels(today=date(2026, 10, 3))
    assert list(seen) == list(idx.INDEX_CODES)
    for code, years in seen.items():
        assert years == list(range(idx.FIRST_YEAR[code], 2027)), code
    written = up.call_args.args[1]
    first = {c: min(r["trade_date"] for r in written if r["index_code"] == c) for c in seen}
    assert first["UTIL"].year == 2005 and first["IBXX"].year == 1994 and first["IFIX"].year == 2010


@pytest.mark.asyncio
async def test_one_index_that_stays_null_stops_the_ingest_before_any_write(monkeypatch, audit_log):
    monkeypatch.setattr(idx, "INDEX_DIVISOR_STEPS", {})  # one stub session a year
    fetcher = MagicMock()
    fetcher.sleep_between = 0

    def fetch_year(code, year):
        if code == "IBXL":
            raise B3IndexNoResults(f"results=null for {code} {year} on all 3 attempts")
        return _grid({date(year, 6, 1): "1.000,00"})

    fetcher.fetch_year.side_effect = fetch_year
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher", return_value=fetcher), \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels") as up:
        with pytest.raises(B3IndexNoResults):
            await ing.ingest_index_levels(today=date(2026, 10, 3))
    up.assert_not_called()
    assert audit_log.finished[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_a_null_year_is_an_error_and_nothing_is_written(monkeypatch, audit_log):
    monkeypatch.setitem(idx.FIRST_YEAR, "IBOV", 2024)
    payloads = {
        2024: B3IndexNoResults("results=null for IBOV 2024"),
        2025: _grid({date(2025, 12, 30): "161.125,37"}),
    }
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher",
               return_value=_fetcher_serving(payloads)), \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels") as up:
        with pytest.raises(B3IndexNoResults):
            await ing.ingest_index_levels(("IBOV",), today=date(2025, 12, 31))
    up.assert_not_called()
    row = audit_log.finished[-1]
    assert row["status"] == "error" and row["rows"] == 0 and "results=null" in row["error"]


@pytest.mark.asyncio
async def test_the_current_year_may_be_null_in_the_first_days_of_january(monkeypatch):
    monkeypatch.setitem(idx.FIRST_YEAR, "IBOV", 2026)
    payloads = {
        2026: _grid({date(2026, 12, 30): "190.000,00"}),
        2027: B3IndexNoResults("results=null for IBOV 2027"),
    }
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher",
               return_value=_fetcher_serving(payloads)), \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels", return_value=1) as up:
        assert await ing.ingest_index_levels(("IBOV",), today=date(2027, 1, 3)) == 1
    assert len(up.call_args.args[1]) == 1


@pytest.mark.asyncio
async def test_an_unexplained_jump_stops_the_ingest_before_any_write(monkeypatch, audit_log):
    monkeypatch.setitem(idx.FIRST_YEAR, "IBOV", 2024)
    payloads = {
        2024: _grid({date(2024, 12, 30): "120.000,00"}),
        2025: _grid({date(2025, 1, 2): "12.000,00"}),
    }
    ing = _ingestor()
    with patch("src.fetchers.b3_index_fetcher.B3IndexFetcher",
               return_value=_fetcher_serving(payloads)), \
         patch("src.pipeline.ingest_b3_index.ingest_b3_index_levels") as up:
        with pytest.raises(ValueError, match="not a listed divisor step"):
            await ing.ingest_index_levels(("IBOV",), today=date(2025, 6, 1))
    up.assert_not_called()
    row = audit_log.finished[-1]
    assert row["status"] == "error" and row["error"]


def test_ingest_upserts_on_the_natural_key():
    records = _series((date(2025, 12, 30), "161125.37"))
    with patch("src.store.pg_client.upsert_rows", return_value=1) as upsert:
        assert idx.ingest_b3_index_levels(MagicMock(), records) == 1
    _, table, rows, conflict = upsert.call_args.args
    assert (table, conflict) == ("b3_index_level", "index_code,trade_date")
    assert rows is records


def test_ingest_of_nothing_writes_nothing():
    with patch("src.store.pg_client.upsert_rows") as upsert:
        assert idx.ingest_b3_index_levels(MagicMock(), []) == 0
    upsert.assert_not_called()


def test_migration_55_and_schema_agree_on_the_key_and_the_check():
    root = Path(__file__).resolve().parents[1]
    for text in (
        (root / "src/store/migrations/55_b3_index_level.sql").read_text(),
        (root / "src/store/schema.sql").read_text(),
    ):
        assert "CREATE TABLE IF NOT EXISTS b3_index_level" in text
        assert "CONSTRAINT uq_b3_index_level UNIQUE (index_code, trade_date)" in text
        assert "CHECK (level > 0)" in text
