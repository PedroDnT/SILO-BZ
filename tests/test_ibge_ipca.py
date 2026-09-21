"""IBGE SIDRA: the IPCA item tree with weights (tables 1419 + 7060).

HTTP is mocked with the documented response shape (a header row first, then
one observation per variable × month × item). The contract these pin was
verified live on 2026-09-21 — see src/fetchers/ibge_sidra_fetcher.py.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Callable, List
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetchers.ibge_sidra_fetcher import (
    SidraFetchError, fetch_ipca_items, parse_ipca_items, table_windows,
)
from src.pipeline.ibge_pipeline import (
    CONFLICT_COLUMNS, LOG_DOC_TYPE, LOG_ENTITY, TABLE, IbgeIngestor,
)

HEADER = {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)",
          "MN": "Unidade de Medida", "V": "Valor", "D1C": "Brasil (Código)", "D1N": "Brasil",
          "D2C": "Variável (Código)", "D2N": "Variável", "D3C": "Mês (Código)", "D3N": "Mês",
          "D4C": "Geral, grupo, subgrupo, item e subitem (Código)",
          "D4N": "Geral, grupo, subgrupo, item e subitem"}


def _obs(var: str, month: str, code: str, name: str, value: str) -> dict:
    return {"NC": "1", "NN": "Brasil", "MC": "2", "MN": "%", "V": value, "D1C": "1", "D1N": "Brasil",
            "D2C": var, "D2N": "IPCA", "D3C": month, "D3N": month, "D4C": code, "D4N": name}


# The 2026-08 figures as SIDRA printed them (live, 2026-09-21).
AUG = [
    _obs("63", "202608", "7169", "Índice geral", "-0.32"),
    _obs("66", "202608", "7169", "Índice geral", "100.0000"),
    _obs("69", "202608", "7169", "Índice geral", "3.11"),
    _obs("2265", "202608", "7169", "Índice geral", "4.22"),
    _obs("63", "202608", "7170", "1.Alimentação e bebidas", "-0.34"),
    _obs("66", "202608", "7170", "1.Alimentação e bebidas", "21.5115"),
    _obs("69", "202608", "7170", "1.Alimentação e bebidas", "3.52"),
    _obs("2265", "202608", "7170", "1.Alimentação e bebidas", "3.53"),
    _obs("63", "202608", "7171", "11.Alimentação no domicílio", "-0.80"),
    _obs("66", "202608", "7171", "11.Alimentação no domicílio", "15.7"),
    _obs("63", "202608", "7172", "1101.Cereais, leguminosas e oleaginosas", "-1.2"),
    _obs("66", "202608", "7172", "1101.Cereais, leguminosas e oleaginosas", "0.9"),
    _obs("63", "202608", "7173", "1101002.Arroz", "1.34"),
    _obs("66", "202608", "7173", "1101002.Arroz", "0.5018"),
    _obs("69", "202608", "7173", "1101002.Arroz", "0.39"),
    _obs("2265", "202608", "7173", "1101002.Arroz", "-8.85"),
    # A code that is not part of this table's structure: empty name, "..." values.
    _obs("63", "202608", "1101002", "", "..."),
    _obs("66", "202608", "1101002", "", "..."),
]


def _client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


@pytest.fixture
def one_attempt(monkeypatch):
    monkeypatch.setenv("IBGE_SIDRA_MAX_RETRIES", "1")
    monkeypatch.setenv("IBGE_SIDRA_RETRY_DELAY", "0")


# ---------------------------------------------------------------------------
# Request planning
# ---------------------------------------------------------------------------

def test_each_table_is_clipped_to_its_own_span_and_cut_by_calendar_year():
    plan = table_windows(date(2018, 6, 1), date(2021, 3, 15))
    assert plan == [
        (1419, "201806", "201812"),
        (1419, "201901", "201912"),
        (7060, "202001", "202012"),
        (7060, "202101", "202103"),
    ]


def test_months_before_2012_have_no_table():
    assert table_windows(date(2005, 1, 1), date(2011, 12, 1)) == []
    assert table_windows(date(2011, 6, 1), date(2012, 2, 1)) == [(1419, "201201", "201202")]


def test_the_daily_window_is_one_request_on_the_current_table():
    assert table_windows(date(2026, 8, 1), date(2026, 9, 1)) == [(7060, "202608", "202609")]
    # A December→January window is two calendar years, hence two requests.
    assert table_windows(date(2025, 12, 1), date(2026, 1, 1)) == [
        (7060, "202512", "202512"), (7060, "202601", "202601"),
    ]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_request_carries_table_variables_period_and_the_whole_tree(one_attempt):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[HEADER] + AUG)

    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await fetch_ipca_items(7060, "202508", "202608")
    assert seen == [
        "https://apisidra.ibge.gov.br/values/t/7060/n1/all/v/63,66,69,2265/p/202508-202608/c315/all?formato=json"
    ]
    assert rows == AUG, "the header row is dropped, nothing else is"


@pytest.mark.asyncio
async def test_an_unpublished_month_is_header_only_and_returns_nothing(one_attempt):
    """Verified live: /p/202609 on 2026-09-21 answers 200 with the header row."""
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(200, json=[HEADER]))):
        assert await fetch_ipca_items(7060, "202609", "202609") == []


@pytest.mark.asyncio
async def test_a_persistent_500_raises_rather_than_reading_as_unpublished(one_attempt):
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(500, text="boom"))):
        with pytest.raises(SidraFetchError, match="failed after 1 attempts"):
            await fetch_ipca_items(7060, "202608", "202608")


@pytest.mark.asyncio
async def test_a_body_without_the_documented_header_raises(one_attempt):
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(200, json=[{"V": "-0.32"}]))):
        with pytest.raises(SidraFetchError, match="documented header"):
            await fetch_ipca_items(7060, "202608", "202608")
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(200, json={"error": 1}))):
        with pytest.raises(SidraFetchError, match="expected a non-empty JSON list"):
            await fetch_ipca_items(7060, "202608", "202608")


@pytest.mark.asyncio
async def test_an_html_200_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setenv("IBGE_SIDRA_MAX_RETRIES", "2")
    monkeypatch.setenv("IBGE_SIDRA_RETRY_DELAY", "0")
    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(200, text="<html>overloaded</html>")
        return httpx.Response(200, json=[HEADER] + AUG[:4])

    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await fetch_ipca_items(7060, "202608", "202608")
    assert n["calls"] == 2 and len(rows) == 4


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def test_observations_pivot_to_one_row_per_month_and_item_with_the_level_read_off_the_number():
    rows, skipped = parse_ipca_items(AUG, 7060)
    assert skipped == 2, "the out-of-structure code is skipped and counted, never stored"
    by_code = {r["item_code"]: r for r in rows}
    assert set(by_code) == {7169, 7170, 7171, 7172, 7173}

    geral = by_code[7169]
    assert geral == {
        "reference_month": "2026-08-01", "item_code": 7169, "item_number": None,
        "item_name": "Índice geral", "level": 0,
        "variacao_mensal": -0.32, "peso_mensal": 100.0,
        "variacao_acum_ano": 3.11, "variacao_acum_12m": 4.22, "sidra_table": 7060,
    }
    assert (by_code[7170]["item_number"], by_code[7170]["level"], by_code[7170]["item_name"]) == \
        ("1", 1, "Alimentação e bebidas")
    assert (by_code[7171]["item_number"], by_code[7171]["level"]) == ("11", 2)
    assert (by_code[7172]["item_number"], by_code[7172]["level"]) == ("1101", 3)
    assert (by_code[7173]["item_number"], by_code[7173]["level"], by_code[7173]["item_name"]) == \
        ("1101002", 4, "Arroz")
    # Variables the sample did not carry stay NULL — never 0.
    assert by_code[7171]["variacao_acum_ano"] is None
    assert by_code[7171]["variacao_acum_12m"] is None


def test_ibges_not_available_markers_are_null_and_garbage_raises():
    rows, _ = parse_ipca_items([_obs("66", "201912", "7170", "1.Alimentação e bebidas", "...")], 1419)
    assert rows[0]["peso_mensal"] is None and rows[0]["sidra_table"] == 1419
    rows, _ = parse_ipca_items([_obs("66", "201912", "7170", "1.Alimentação e bebidas", "-")], 1419)
    assert rows[0]["peso_mensal"] is None
    with pytest.raises(SidraFetchError, match="non-numeric"):
        parse_ipca_items([_obs("66", "201912", "7170", "1.Alimentação e bebidas", "n/d")], 1419)


def test_natural_keys_are_never_guessed():
    with pytest.raises(SidraFetchError, match="unparseable month"):
        parse_ipca_items([_obs("63", "2026-08", "7169", "Índice geral", "1")], 7060)
    with pytest.raises(SidraFetchError, match="unparseable item code"):
        parse_ipca_items([_obs("63", "202608", "abc", "Índice geral", "1")], 7060)
    with pytest.raises(SidraFetchError, match="unexpected variable"):
        parse_ipca_items([_obs("99", "202608", "7169", "Índice geral", "1")], 7060)
    with pytest.raises(SidraFetchError, match="unknown length"):
        parse_ipca_items([_obs("63", "202608", "1", "123.Three digits", "1")], 7060)


# ---------------------------------------------------------------------------
# Pipeline + audit
# ---------------------------------------------------------------------------

INGEST_LOG_COLUMNS = {
    "id", "run_id", "entity", "doc_type", "period_year", "period_month",
    "rows_upserted", "status", "error_msg", "started_at", "finished_at",
}


def _ingestor() -> IbgeIngestor:
    with patch("src.pipeline.ibge_pipeline.get_pg_client", return_value=MagicMock()):
        return IbgeIngestor()


@pytest.mark.asyncio
async def test_daily_update_upserts_on_the_natural_key_and_logs_ok():
    ing = _ingestor()
    sent: List[dict] = []
    asked: List[tuple] = []

    async def fake_fetch(table, period_from, period_to):
        asked.append((table, period_from, period_to))
        return AUG if period_to >= "202608" else []

    def fake_upsert(conn, table, rows, **kw):
        sent.append({"table": table, "rows": rows, "conflict": kw.get("conflict_columns")})
        return len(rows)

    with patch("src.pipeline.ibge_pipeline.fetch_ipca_items", fake_fetch), \
         patch("src.pipeline.ibge_pipeline.upsert_rows", fake_upsert), \
         patch("src.pipeline.ingest_log.upsert_rows", fake_upsert), \
         patch("src.pipeline.ibge_pipeline.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 21)
        fake_date.side_effect = lambda *a, **k: date(*a, **k)
        fake_date.fromisoformat = date.fromisoformat
        totals = await ing.daily_update()

    assert asked == [(7060, "202608", "202609")]
    data = [s for s in sent if s["table"] == TABLE]
    assert len(data) == 1 and data[0]["conflict"] == CONFLICT_COLUMNS == "reference_month,item_code"
    assert len(data[0]["rows"]) == 5
    assert totals == {TABLE: 5}

    log = [s["rows"][0] for s in sent if s["table"] == "cvm_ingest_log"]
    assert [r["status"] for r in log] == ["running", "ok"]
    assert log[-1]["rows_upserted"] == 5
    assert (log[-1]["entity"], log[-1]["doc_type"]) == (LOG_ENTITY, LOG_DOC_TYPE) == ("ibge", "ipca_item")
    assert (log[0]["period_year"], log[0]["period_month"]) == (2026, 8), "keyed on the window start"
    for row in log:
        assert not set(row) - INGEST_LOG_COLUMNS, set(row) - INGEST_LOG_COLUMNS


@pytest.mark.asyncio
async def test_a_fetch_failure_lands_an_error_row_and_raises():
    ing = _ingestor()
    sent: List[dict] = []

    async def fake_fetch(table, period_from, period_to):
        raise SidraFetchError("SIDRA t/7060: HTTP 503")

    def fake_upsert(conn, table, rows, **kw):
        sent.append({"table": table, "rows": rows})
        return len(rows)

    with patch("src.pipeline.ibge_pipeline.fetch_ipca_items", fake_fetch), \
         patch("src.pipeline.ibge_pipeline.upsert_rows", fake_upsert), \
         patch("src.pipeline.ingest_log.upsert_rows", fake_upsert):
        with pytest.raises(SidraFetchError):
            await ing.backfill(start="2026-01-01")

    log = [s["rows"][0] for s in sent if s["table"] == "cvm_ingest_log"]
    assert log[-1]["status"] == "error"
    assert "HTTP 503" in log[-1]["error_msg"]
    assert not [s for s in sent if s["table"] == TABLE]


@pytest.mark.asyncio
async def test_backfill_walks_both_tables_from_2012():
    ing = _ingestor()
    asked: List[tuple] = []

    async def fake_fetch(table, period_from, period_to):
        asked.append((table, period_from, period_to))
        return []

    async def fake_audited(client, entity, doc_type, fn, **kw):
        return await fn()

    with patch("src.pipeline.ibge_pipeline.fetch_ipca_items", fake_fetch), \
         patch("src.pipeline.ibge_pipeline.audited", fake_audited), \
         patch("src.pipeline.ibge_pipeline.date") as fake_date:
        fake_date.today.return_value = date(2026, 9, 21)
        fake_date.side_effect = lambda *a, **k: date(*a, **k)
        fake_date.fromisoformat = date.fromisoformat
        totals = await ing.backfill()

    tables = [t for t, _, _ in asked]
    assert tables.count(1419) == 8 and tables.count(7060) == 7, asked
    assert asked[0] == (1419, "201201", "201212") and asked[-1] == (7060, "202601", "202609")
    assert totals == {TABLE: 0}
