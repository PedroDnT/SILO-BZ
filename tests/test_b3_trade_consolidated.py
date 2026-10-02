"""Offline tests for B3's consolidated trade file, segment FORWARD (migration 57).

The fixture is a verbatim excerpt of TradeInformationConsolidatedFile for
2026-09-29, captured 2026-09-30: the status line, the header, six FORWARD
rows (fixed income ETFs, two of them absent from cvm_etf_registry), two CASH
rows and two untraded option rows. Variants are built from it in each test.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.fetchers.b3_trade_consolidated_fetcher import (
    B3TradeConsolidatedEmpty,
    B3TradeConsolidatedFetcher,
    B3TradeConsolidatedFetchError,
    B3TradeConsolidatedNoSession,
)
from src.pipeline import ingest_b3_trade_consolidated as tc
from src.pipeline.b3_pipeline import B3Ingestor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/b3_trade_consolidated/2026-09-29_excerpt.csv"
SESSION = date(2026, 9, 29)


def _text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# ------------------------------------------------------------------ parse


def test_only_forward_rows_are_kept():
    rows, dropped = tc.parse(_text(), SESSION)
    assert dropped == 0
    assert sorted(r["ticker"] for r in rows) == [
        "B5P211", "BLFT11", "IMAB11", "LFTS11", "NTNF11", "SELI11",
    ]
    assert {r["segment"] for r in rows} == {"FORWARD"}


def test_imab11_is_stored_as_published():
    rows, _ = tc.parse(_text(), SESSION)
    imab = next(r for r in rows if r["ticker"] == "IMAB11")
    assert imab == {
        "trade_date": SESSION,
        "ticker": "IMAB11",
        "isin": "BRIMABCTF004",
        "segment": "FORWARD",
        "min_price": Decimal("118.39"),
        "max_price": Decimal("119.28"),
        "avg_price": Decimal("118.86"),
        "last_price": Decimal("119.16"),
        "oscillation_pct": Decimal("0.65"),
        "adjusted_qty": None,
        "adjusted_qty_tax": None,
        "ref_price": None,
        "trade_count": 2601,
        "quantity": 30079,
        "notional_brl": Decimal("3575098.33"),
        "file_status": "Final",
        "source": "b3_trade_consolidated_file",
    }


def test_there_is_no_opening_price():
    """The source has none; the row must not grow one."""
    rows, _ = tc.parse(_text(), SESSION)
    assert all("open_price" not in r for r in rows)


def test_an_untraded_row_keeps_null_prices_and_its_reference():
    text = _text() + "2026-09-29;XB3011;BRXB30CTF000;FORWARD;;;;;;;;100,5;;;\n"
    rows, _ = tc.parse(text, SESSION)
    row = next(r for r in rows if r["ticker"] == "XB3011")
    assert row["last_price"] is None and row["min_price"] is None
    assert row["ref_price"] == Decimal("100.5")
    assert row["trade_count"] is None


def test_a_file_not_marked_final_is_not_stored():
    text = _text().replace("Status do Arquivo: Final", "Status do Arquivo: Preliminar", 1)
    with pytest.raises(tc.B3TradeConsolidatedNotFinal):
        tc.parse(text, SESSION)


def test_a_misdated_row_raises():
    with pytest.raises(tc.B3TradeConsolidatedParseError, match="dated 2026-09-29"):
        tc.parse(_text(), date(2026, 9, 28))


def test_a_file_with_no_forward_row_raises():
    text = "\n".join(l for l in _text().splitlines() if ";FORWARD;" not in l)
    with pytest.raises(tc.B3TradeConsolidatedParseError, match="no usable FORWARD row"):
        tc.parse(text, SESSION)


def test_a_changed_header_raises():
    text = _text().replace("LastPric", "ClsgPric", 1)
    with pytest.raises(tc.B3TradeConsolidatedParseError, match="LastPric"):
        tc.parse(text, SESSION)


def test_invalid_rows_are_dropped_and_counted_not_coerced():
    bad = (
        "2026-09-29;BAD11;BRBADXCTF000;FORWARD;0;1;1;1;;;;;1;1;1\n"      # zero price
        "2026-09-29;FRAC11;BRFRACCTF000;FORWARD;1;1;1;1;;;;;1,5;1;1\n"   # fractional count
        "2026-09-29;SHORT11;BRSHORCTF000;FORWARD;1\n"                    # truncated
    )
    rows, dropped = tc.parse(_text() + bad, SESSION)
    assert dropped == 3
    assert not {"BAD11", "FRAC11", "SHORT11"} & {r["ticker"] for r in rows}


# ------------------------------------------------------------------ fetch


def _transport(handler):
    return httpx.MockTransport(handler)


def _fetcher_with(handler) -> B3TradeConsolidatedFetcher:
    fetcher = B3TradeConsolidatedFetcher(max_retries=2, retry_delay=0)
    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=_transport(handler), **kwargs)

    patcher = patch("src.fetchers.b3_trade_consolidated_fetcher.httpx.AsyncClient", client)
    patcher.start()
    return fetcher, patcher


async def test_fetch_follows_the_token_to_the_file():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path == "/api/download/requestname":
            assert request.url.params["date"] == "2026-09-29"
            assert request.url.params["recaptchaToken"] == ""
            return httpx.Response(200, json={"redirectUrl": "~/download?token=abc"})
        assert request.url.path == "/api/download/"
        assert request.url.params["token"] == "abc"
        return httpx.Response(200, content=FIXTURE.read_bytes())

    fetcher, patcher = _fetcher_with(handler)
    try:
        body = await fetcher.fetch(SESSION)
    finally:
        patcher.stop()
    assert body.startswith(b"Status do Arquivo: Final")
    assert len(seen) == 2


async def test_an_empty_file_is_empty_not_an_error():
    def handler(request):
        if request.url.path.endswith("requestname"):
            return httpx.Response(200, json={"redirectUrl": "~/download?token=abc"})
        return httpx.Response(200, content=b"")

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedEmpty):
            await fetcher.fetch(date(2025, 6, 9))
    finally:
        patcher.stop()


# Verbatim shape of B3's answer for 2026-09-07 (a holiday), 2026-09-27 (a
# Sunday) and 2026-10-01 (the future), captured 2026-09-30.
_NO_SESSION = {
    "type": "https://tools.ietf.org/html/rfc9110#section-15.5.1",
    "title": "Bad Request",
    "status": 400,
    "traceId": "00-e5552335109b35ea7cf1f92c36e8c781-4098cf8b0225e122-00",
}


async def test_a_day_with_no_session_is_no_session_not_an_error():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(400, json=_NO_SESSION)

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedNoSession):
            await fetcher.fetch(date(2026, 9, 7))
    finally:
        patcher.stop()
    assert calls == ["/api/download/requestname"]  # not retried


async def test_a_400_that_is_not_b3s_problem_body_is_an_error():
    def handler(request):
        return httpx.Response(400, text="could not be converted")

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedFetchError, match="HTTP 400"):
            await fetcher.fetch(SESSION)
    finally:
        patcher.stop()


async def test_an_html_page_is_an_error_never_a_file():
    def handler(request):
        if request.url.path.endswith("requestname"):
            return httpx.Response(200, json={"redirectUrl": "~/download?token=abc"})
        return httpx.Response(200, content=b"<!DOCTYPE html>\n<html lang='pt-BR'>")

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedFetchError, match="HTML"):
            await fetcher.fetch(SESSION)
    finally:
        patcher.stop()


async def test_a_missing_token_raises():
    def handler(request):
        return httpx.Response(200, json={"error": "recaptcha"})

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedFetchError, match="no download token"):
            await fetcher.fetch(SESSION)
    finally:
        patcher.stop()


async def test_a_rate_limit_is_retried_then_raises():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403)

    fetcher, patcher = _fetcher_with(handler)
    try:
        with pytest.raises(B3TradeConsolidatedFetchError, match="failed after 2 attempts"):
            await fetcher.fetch(SESSION)
    finally:
        patcher.stop()
    assert len(calls) == 2


# ------------------------------------------------------------------ ingest


def _ingestor(fetch: AsyncMock) -> B3Ingestor:
    with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()):
        fetcher = MagicMock()
        fetcher.fetch = fetch
        return B3Ingestor(fetcher=MagicMock(), bdi_fetcher=MagicMock(),
                          trade_consolidated_fetcher=fetcher)


async def test_ingest_upserts_on_the_natural_key_and_logs_ok(audit_log):
    ing = _ingestor(AsyncMock(return_value=FIXTURE.read_bytes()))
    with patch("src.pipeline.b3_pipeline.upsert_rows", return_value=6) as up:
        assert await ing.ingest_trade_consolidated(SESSION) == 6
    _, table, rows = up.call_args.args
    assert table == "b3_trade_consolidated"
    assert up.call_args.kwargs["conflict_columns"] == "ticker,trade_date"
    assert len(rows) == 6
    assert [r["doc_type"] for r in audit_log.started] == ["trade_consolidated"]
    (row,) = audit_log.finished
    assert (row["status"], row["rows"], row["error"]) == ("ok", 6, None)


async def test_an_empty_session_is_logged_skipped_and_writes_nothing(audit_log):
    ing = _ingestor(AsyncMock(side_effect=B3TradeConsolidatedEmpty("empty")))
    with patch("src.pipeline.b3_pipeline.upsert_rows") as up:
        assert await ing.ingest_trade_consolidated(date(2025, 6, 9)) == 0
    up.assert_not_called()
    assert audit_log.finished[-1]["status"] == "skipped"


async def test_a_fetch_failure_is_logged_and_raised(audit_log):
    ing = _ingestor(AsyncMock(side_effect=B3TradeConsolidatedFetchError("HTTP 500")))
    with patch("src.pipeline.b3_pipeline.upsert_rows") as up:
        with pytest.raises(B3TradeConsolidatedFetchError):
            await ing.ingest_trade_consolidated(SESSION)
    up.assert_not_called()
    row = audit_log.finished[-1]
    assert row["status"] == "error" and "HTTP 500" in row["error"]


async def test_a_no_session_day_is_logged_skipped(audit_log):
    ing = _ingestor(AsyncMock(side_effect=B3TradeConsolidatedNoSession("400")))
    with patch("src.pipeline.b3_pipeline.upsert_rows") as up:
        assert await ing.ingest_trade_consolidated(date(2026, 9, 7)) == 0
    up.assert_not_called()
    assert audit_log.finished[-1]["status"] == "skipped"


_NO_PAUSE = patch("src.pipeline.b3_pipeline.asyncio.sleep", AsyncMock())


async def test_the_daily_window_raises_when_no_weekday_lands_a_row():
    """Every day skipped is a changed contract more likely than a closed week."""
    ing = _ingestor(AsyncMock())
    with _NO_PAUSE, patch.object(ing, "ingest_trade_consolidated", AsyncMock(return_value=0)):
        with pytest.raises(RuntimeError, match="no row landed"):
            await ing.daily_update_trade_consolidated()


async def test_the_daily_window_requests_weekdays_and_sums():
    ing = _ingestor(AsyncMock())
    with _NO_PAUSE, patch.object(ing, "ingest_trade_consolidated", AsyncMock(return_value=67)) as one:
        totals = await ing.daily_update_trade_consolidated()
    sessions = [c.args[0] for c in one.call_args_list]
    assert sessions and all(s.weekday() < 5 for s in sessions)
    assert totals == {"b3_trade_consolidated": 67 * len(sessions)}


async def test_backfill_requests_weekdays_only():
    ing = _ingestor(AsyncMock())
    with _NO_PAUSE, patch.object(ing, "ingest_trade_consolidated", AsyncMock(return_value=1)) as one:
        # 2026-09-25 is a Friday, 2026-09-28 a Monday.
        totals = await ing.backfill_trade_consolidated(date(2026, 9, 25), date(2026, 9, 28))
    assert [c.args[0] for c in one.call_args_list] == [date(2026, 9, 25), date(2026, 9, 28)]
    assert totals == {"b3_trade_consolidated": 2}


# ------------------------------------------------------------------ schema


def test_migration_57_and_schema_agree_on_the_key():
    for path in ("src/store/migrations/57_b3_trade_consolidated.sql", "src/store/schema.sql"):
        text = (ROOT / path).read_text()
        assert "CREATE TABLE IF NOT EXISTS b3_trade_consolidated" in text
        assert "CONSTRAINT uq_b3_trade_consolidated UNIQUE (ticker, trade_date)" in text
        assert "open_price" not in text.split("b3_trade_consolidated", 1)[1].split(";", 1)[0]
    migration = (ROOT / "src/store/migrations/57_b3_trade_consolidated.sql").read_text()
    assert "REVOKE ALL ON b3_trade_consolidated FROM anon, authenticated" in migration


def test_the_backfill_is_a_dispatch_mode():
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load((ROOT / ".github/workflows/daily_ingest.yml").read_text())
    assert "b3-trade-consolidated" in spec[True]["workflow_dispatch"]["inputs"]["mode"]["options"]
    step = next(s for s in spec["jobs"]["ingest"]["steps"]
                if s.get("name") == "Run B3 consolidated trades backfill")
    assert "--b3-trade-consolidated-start" in step["run"]


def test_a_file_missing_the_whole_cash_market_is_incomplete_not_a_format_change():
    """2025-08-13: marked Final, a normal session in COTAHIST, but B3's file
    carries only options, FINANCIAL and AGRIBUSINESS."""
    lines = _text().splitlines()
    kept = lines[:2] + [l for l in lines[2:] if ";FORWARD;" not in l and ";CASH;" not in l]
    with pytest.raises(tc.B3TradeConsolidatedIncomplete, match="cash market is missing"):
        tc.parse("\n".join(kept), SESSION)


async def test_an_incomplete_file_is_logged_skipped(audit_log):
    lines = _text().splitlines()
    kept = lines[:2] + [l for l in lines[2:] if ";FORWARD;" not in l and ";CASH;" not in l]
    ing = _ingestor(AsyncMock(return_value="\n".join(kept).encode()))
    with patch("src.pipeline.b3_pipeline.upsert_rows") as up:
        assert await ing.ingest_trade_consolidated(SESSION) == 0
    up.assert_not_called()
    assert audit_log.finished[-1]["status"] == "skipped"


async def test_the_backfill_continues_past_a_failed_session_then_raises():
    ing = _ingestor(AsyncMock())
    calls = []

    async def one(session):
        calls.append(session)
        if session == date(2026, 9, 28):
            raise RuntimeError("boom")
        return 1

    with _NO_PAUSE, patch.object(ing, "ingest_trade_consolidated", side_effect=one):
        with pytest.raises(RuntimeError, match="1 session\\(s\\) failed; first: 2026-09-28: boom"):
            await ing.backfill_trade_consolidated(date(2026, 9, 25), date(2026, 9, 29))
    assert calls == [date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29)]
