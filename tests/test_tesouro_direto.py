"""Tesouro Direto: the Treasury's daily posted rates and prices per title.

The fixture copies rows of the live file as it read on 2026-11-16 (contract in
src/fetchers/tesouro_direto_fetcher.py). HTTP and the database are mocked.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetchers.tesouro_direto_fetcher import (
    CSV_URL, TesouroFetchError, fetch_csv, parse_csv,
)
from src.pipeline.tesouro_pipeline import (
    CONFLICT_COLUMNS, LOG_DOC_TYPE, LOG_ENTITY, TABLE, TesouroIngestor,
)

HEADER = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha"
)
CSV = "\n".join([
    HEADER,
    "Tesouro Selic;01/03/2031;13/11/2026;0,11;0,12;20211,26;20192,26;20192,26",
    "Tesouro Selic;01/03/2027;03/09/2026;-0,00;0,01;19813,70;19802,47;19802,47",
    "Tesouro IPCA+ com Juros Semestrais;15/08/2020;14/08/2020;-1,78;-1,66;0,00;0,00;3407,83",
    "Tesouro Prefixado com Juros Semestrais;01/01/2008;31/12/2004;17,14;17,24;849,02;847,13;895,37",
    "Tesouro IPCA+;15/05/2035;13/11/2026;7,51;7,63;1.765,32;1.748,01;1.748,01",
]).encode("ascii")


def test_rows_parse_with_the_natural_key_and_published_values():
    rows, dropped = parse_csv(CSV)
    assert dropped == 0
    assert len(rows) == 5
    first = rows[0]
    assert first == {
        "tipo_titulo": "Tesouro Selic",
        "data_vencimento": date(2031, 3, 1),
        "data_base": date(2026, 11, 13),
        "taxa_compra": Decimal("0.11"),
        "taxa_venda": Decimal("0.12"),
        "pu_compra": Decimal("20211.26"),
        "pu_venda": Decimal("20192.26"),
        "pu_base": Decimal("20192.26"),
    }


def test_negative_rates_are_kept_and_a_zero_price_is_null():
    rows, _ = parse_csv(CSV)
    ipca_2020 = rows[2]
    assert ipca_2020["taxa_compra"] == Decimal("-1.78")
    assert ipca_2020["pu_compra"] is None
    assert ipca_2020["pu_venda"] is None
    assert ipca_2020["pu_base"] == Decimal("3407.83")


def test_thousands_separator_from_the_metadata_sheet_parses():
    rows, _ = parse_csv(CSV)
    assert rows[4]["pu_compra"] == Decimal("1765.32")


def test_since_keeps_recent_base_dates_only():
    rows, _ = parse_csv(CSV, since=date(2026, 11, 1))
    assert {r["data_base"] for r in rows} == {date(2026, 11, 13)}


def test_a_bad_row_is_dropped_and_counted_never_guessed():
    bad = CSV + b"\nTesouro Selic;31/02/2031;13/11/2026;0,11;0,12;1,00;1,00;1,00" \
                b"\nTesouro Selic;01/03/2031;12/11/2026;n/d;0,12;1,00;1,00;1,00" \
                b"\nTesouro Selic;01/03/2031;11/11/2026;0,11;0,12;-1,00;1,00;1,00" \
                b"\n;01/03/2031;10/11/2026;0,11;0,12;1,00;1,00;1,00"
    rows, dropped = parse_csv(bad)
    assert len(rows) == 5
    assert dropped == 4


def test_a_changed_header_raises():
    with pytest.raises(TesouroFetchError, match="unexpected header"):
        parse_csv(CSV.replace(b"PU Base Manha", b"PU Base Tarde"))


def test_a_header_only_file_raises():
    with pytest.raises(TesouroFetchError, match="no rows"):
        parse_csv(HEADER.encode())


@pytest.fixture
def one_attempt(monkeypatch):
    monkeypatch.setenv("TESOURO_MAX_RETRIES", "1")
    monkeypatch.setenv("TESOURO_RETRY_DELAY", "0")


def _client_factory(handler):
    real = httpx.AsyncClient
    return lambda **kw: real(transport=httpx.MockTransport(handler), **kw)


@pytest.mark.asyncio
async def test_fetch_returns_the_body(one_attempt):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=CSV)

    with patch("httpx.AsyncClient", _client_factory(handler)):
        assert await fetch_csv() == CSV
    assert seen == [CSV_URL]


@pytest.mark.asyncio
async def test_a_persistent_error_raises(one_attempt):
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(503))):
        with pytest.raises(TesouroFetchError, match="failed after 1 attempts"):
            await fetch_csv()
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(404, text="gone"))):
        with pytest.raises(TesouroFetchError, match="HTTP 404"):
            await fetch_csv()


@pytest.mark.asyncio
async def test_a_refused_connection_names_the_error_class(one_attempt):
    def handler(request):
        raise httpx.ConnectError("")

    with patch("httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(TesouroFetchError, match="failed after 1 attempts: ConnectError"):
            await fetch_csv()


def test_the_default_retry_budget_waits_minutes_not_seconds(monkeypatch):
    from src.fetchers.tesouro_direto_fetcher import _retry_config

    monkeypatch.delenv("TESOURO_MAX_RETRIES", raising=False)
    monkeypatch.delenv("TESOURO_RETRY_DELAY", raising=False)
    attempts, delay = _retry_config()
    # linear backoff waits delay * n after try n, never after the last
    assert sum(delay * n for n in range(1, attempts)) >= 5 * 60


@pytest.mark.asyncio
async def test_daily_update_upserts_the_window_on_the_natural_key_and_logs_ok():
    upserts = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        upserts.append((table, rows, conflict_columns))
        return len(rows)

    async def fake_fetch():
        return CSV

    with patch("src.pipeline.tesouro_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.tesouro_pipeline.fetch_csv", fake_fetch), \
         patch("src.pipeline.tesouro_pipeline.upsert_rows", fake_upsert), \
         patch("src.pipeline.ingest_log.upsert_rows", fake_upsert), \
         patch("src.pipeline.tesouro_pipeline.date") as fake_date:
        fake_date.today.return_value = date(2026, 11, 16)
        totals = await TesouroIngestor().daily_update()

    assert totals == {TABLE: 2}
    data = [u for u in upserts if u[0] == TABLE]
    assert len(data) == 1
    assert data[0][2] == CONFLICT_COLUMNS == "tipo_titulo,data_vencimento,data_base"
    assert {r["data_base"] for r in data[0][1]} == {date(2026, 11, 13)}
    log = [u for u in upserts if u[0] == "cvm_ingest_log"]
    assert log and log[-1][1][0]["entity"] == LOG_ENTITY
    assert log[-1][1][0]["doc_type"] == LOG_DOC_TYPE
    assert log[-1][1][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_backfill_upserts_every_row():
    async def fake_fetch():
        return CSV

    captured = {}

    def fake_upsert(client, table, rows, conflict_columns=None):
        captured.setdefault(table, []).extend(rows)
        return len(rows)

    with patch("src.pipeline.tesouro_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.tesouro_pipeline.fetch_csv", fake_fetch), \
         patch("src.pipeline.tesouro_pipeline.upsert_rows", fake_upsert), \
         patch("src.pipeline.ingest_log.upsert_rows", fake_upsert):
        totals = await TesouroIngestor().backfill()
    assert totals == {TABLE: 5}


@pytest.mark.asyncio
async def test_a_fetch_failure_lands_an_error_row_and_raises():
    async def fake_fetch():
        raise TesouroFetchError("Tesouro Direto: HTTP 404: gone")

    logged = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        logged.extend(rows)
        return len(rows)

    with patch("src.pipeline.tesouro_pipeline.get_pg_client", return_value=MagicMock()), \
         patch("src.pipeline.tesouro_pipeline.fetch_csv", fake_fetch), \
         patch("src.pipeline.tesouro_pipeline.upsert_rows", fake_upsert), \
         patch("src.pipeline.ingest_log.upsert_rows", fake_upsert):
        with pytest.raises(TesouroFetchError):
            await TesouroIngestor().daily_update()
    assert logged and logged[-1]["status"] == "error"
