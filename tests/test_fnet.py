"""FNET (B3 Fundos.NET) document register — backlog B1.

HTTP is mocked. The fixture page is a real FNET response (FIDC, delivery day
2026-09-01, first 5 of 274 rows, fetched 2026-09-24); the contract it pins is
documented in src/fetchers/fnet_fetcher.py.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetchers.fnet_fetcher import FnetFetcher, FnetFetchError, parse_documents
from src.pipeline import fnet_pipeline as fp

FIXTURE = Path(__file__).parent / "fixtures" / "fnet" / "search_fidc_2026-09-01_p1.json"
ROOT = Path(__file__).resolve().parents[1]


def _page() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _row(fnet_id: int, **over: Any) -> Dict[str, Any]:
    r = dict(_page()["data"][0])
    r.update(id=fnet_id, **over)
    return r


def _client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


def _fetcher() -> FnetFetcher:
    return FnetFetcher(max_retries=2, retry_delay=0, min_interval=0)


def _paged(rows: List[Dict[str, Any]], total: int | None = None, page: int = 200):
    """A handler that serves ``rows`` in pages, like FNET, with recordsTotal = total."""
    seen: List[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        s = int(req.url.params.get("s", 0))
        l = int(req.url.params.get("l", page))
        chunk = rows[s:s + min(l, page)]
        return httpx.Response(200, json={"draw": 1, "recordsTotal": len(rows) if total is None else total,
                                         "recordsFiltered": len(rows), "data": chunk})
    return handler, seen


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parse_real_page_keeps_version_fields_and_competencia():
    rows, dropped = parse_documents(_page()["data"])
    assert dropped == 0 and len(rows) == 5
    first = rows[0]
    assert first["fnet_id"] == 1306440
    assert first["versao"] == 1 and first["modalidade"] == "AP" and first["status"] == "AC"
    assert first["tipo_documento"] == "Composição da Carteira (CDA)"
    assert first["reference_raw"] == "08/2026"
    assert first["reference_date"] == date(2026, 8, 1)          # mm/yyyy → first of month
    assert first["delivered_at"] == datetime(2026, 9, 1, 1, 57)  # as printed, São Paulo local
    assert first["raw"]["id"] == 1306440                         # provenance kept whole
    rating = next(r for r in rows if r["fnet_id"] == 1306448)
    assert rating["reference_date"] == date(2026, 8, 18)          # dd/mm/yyyy → that day


@pytest.mark.parametrize("ref", ["2025", "1T2025", "", None, "32/13/2025"])
def test_reference_that_is_not_a_day_or_month_stays_null(ref):
    rows, _ = parse_documents([_row(1, dataReferencia=ref)])
    assert rows[0]["reference_date"] is None
    assert rows[0]["reference_raw"] == (ref.strip() or None if isinstance(ref, str) else None)


@pytest.mark.parametrize("bad", [
    {"id": None}, {"id": "x"}, {"id": 0}, {"versao": None}, {"versao": 0},
    {"dataEntrega": None}, {"dataEntrega": "ontem"},
])
def test_rows_missing_key_fields_are_dropped_and_counted(bad):
    r = _row(5)
    r.update(bad)
    rows, dropped = parse_documents([r, _row(6)])
    assert dropped == 1 and [x["fnet_id"] for x in rows] == [6]


def test_restatement_codes_are_stored_as_published():
    rows, _ = parse_documents([_row(7, versao=3, modalidade="RC", status="IC")])
    assert (rows[0]["versao"], rows[0]["modalidade"], rows[0]["status"]) == (3, "RC", "IC")


# ---------------------------------------------------------------------------
# Fetcher: paging, reconciliation, retries
# ---------------------------------------------------------------------------

async def test_search_walks_every_page_and_sends_day_window():
    rows = [_row(i) for i in range(1, 451)]
    handler, seen = _paged(rows)
    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        got = await _fetcher().search(day=date(2026, 9, 1), tipo_fundo=2)
    assert [r["id"] for r in got] == list(range(1, 451))
    assert [int(r.url.params["s"]) for r in seen] == [0, 200, 400]
    p = seen[0].url.params
    assert p["dataInicial"] == p["dataFinal"] == "01/09/2026"
    assert p["tipoFundo"] == "2" and p["l"] == "200"
    assert seen[0].headers["X-Requested-With"] == "XMLHttpRequest"


async def test_short_walk_raises_instead_of_returning_fewer_rows():
    handler, _ = _paged([_row(i) for i in range(1, 11)], total=12)
    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(FnetFetchError, match="recordsTotal=12"):
            await _fetcher().search(day=date(2026, 9, 1))


async def test_unstable_paging_is_rewalked_until_every_id_is_held():
    """FNET 2026-08-02: an unsorted walk served 3 ids twice and 3 never."""
    rows = [_row(i) for i in range(1, 204)]
    walks = {"n": 0}

    def handler(req):
        s = int(req.url.params["s"])
        if s == 0:
            walks["n"] += 1
        if walks["n"] == 1 and s == 200:
            chunk = rows[197:200]            # the first walk repeats 3 ids, misses 200..202
        else:
            chunk = rows[s:s + 200]
        return httpx.Response(200, json={"draw": 1, "recordsTotal": 203, "recordsFiltered": 203, "data": chunk})

    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        got = await _fetcher().search(day=date(2026, 8, 2))
    assert sorted(r["id"] for r in got) == list(range(1, 204))
    assert walks["n"] == 2


async def test_paging_that_never_completes_raises():
    rows = [_row(i) for i in range(1, 204)]

    def handler(req):
        s = int(req.url.params["s"])
        chunk = rows[197:200] if s == 200 else rows[s:s + 200]
        return httpx.Response(200, json={"draw": 1, "recordsTotal": 203, "recordsFiltered": 203, "data": chunk})

    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(FnetFetchError, match="200 distinct ids after 3 walks"):
            await _fetcher().search(day=date(2026, 8, 2))


async def test_walk_is_sorted_by_delivery_time():
    handler, seen = _paged([_row(1)])
    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        await _fetcher().search(cnpj="07727002000126")
    assert seen[0].url.params["o[0][dataEntrega]"] == "asc"


async def test_retries_a_firewall_520_then_succeeds():
    calls = {"n": 0}
    ok, _ = _paged([_row(1)])

    def handler(req):
        calls["n"] += 1
        return httpx.Response(520, text="error code: 520") if calls["n"] == 1 else ok(req)

    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        got = await _fetcher().search(cnpj="07727002000126")
    assert [r["id"] for r in got] == [1] and calls["n"] == 2


async def test_html_body_with_200_is_retried_then_raises():
    handler = lambda req: httpx.Response(200, text="<html>challenge</html>")  # noqa: E731
    with patch("src.fetchers.fnet_fetcher.httpx.AsyncClient", _client_factory(handler)):
        with pytest.raises(FnetFetchError, match="failed after 2 attempts"):
            await _fetcher().search(day=date(2026, 9, 1))


async def test_unwindowed_query_is_refused():
    with pytest.raises(ValueError, match="533"):
        await _fetcher().search()


@pytest.mark.parametrize("kw", [{"tipo_fundo": 4}, {"cnpj": "123"}])
async def test_bad_filters_are_refused(kw):
    with pytest.raises(ValueError):
        await _fetcher().search(day=date(2026, 9, 1), **kw)


# ---------------------------------------------------------------------------
# Pipeline: register, type labels, fund links
# ---------------------------------------------------------------------------

class _FakeFetcher:
    def __init__(self, by_query: Dict[tuple, List[Dict[str, Any]]]):
        self.by_query = by_query
        self.calls: List[tuple] = []

    async def search(self, *, day=None, tipo_fundo=None, cnpj=None):
        key = (day, tipo_fundo, cnpj)
        self.calls.append(key)
        return self.by_query.get(key, [])


def _ingestor(fetcher) -> tuple:
    captured: Dict[str, List[Dict[str, Any]]] = {}

    def fake_upsert(client, table, rows, conflict_columns=None):
        captured.setdefault(table, []).extend(rows)
        return len(rows)

    with patch.object(fp, "get_pg_client", return_value=MagicMock()):
        ing = fp.FnetIngestor(fetcher=fetcher)
    return ing, captured, patch.object(fp, "upsert_rows", side_effect=fake_upsert)


async def test_ingest_day_stores_register_and_type_labels():
    d = date(2026, 9, 1)
    fake = _FakeFetcher({
        (d, None, None): [_row(1), _row(2), _row(3)],
        (d, 2, None): [_row(1), _row(2)],
        (d, 1, None): [_row(3)],
        (d, 3, None): [_row(99)],   # typed but missing from the unfiltered crawl
    })
    ing, captured, up = _ingestor(fake)
    with up:
        n = await ing.ingest_day(d)
    assert n == 4
    assert sorted(r["fnet_id"] for r in captured[fp.TABLE]) == [1, 2, 3, 99]
    labels = {(r["fnet_id"], r["filter_value"]) for r in captured[fp.FILTER_TABLE]}
    assert labels == {(1, "2"), (2, "2"), (3, "1"), (99, "3")}
    assert all(r["filter_name"] == "tipoFundo" for r in captured[fp.FILTER_TABLE])


async def test_sweep_links_documents_to_the_cnpj_that_was_queried_not_a_name():
    fake = _FakeFetcher({(None, None, "07727002000126"): [_row(10), _row(11)]})
    ing, captured, up = _ingestor(fake)
    with up:
        links = await ing.sweep_funds(["07727002000126", "11728688000147"])
    assert links == 2
    assert {(r["fnet_id"], r["filter_name"], r["filter_value"]) for r in captured[fp.FILTER_TABLE]} == {
        (10, "cnpjFundo", "07727002000126"), (11, "cnpjFundo", "07727002000126")}
    assert fake.calls == [(None, None, "07727002000126"), (None, None, "11728688000147")]


def test_sweep_slices_partition_the_universe_and_are_stable():
    cnpjs = [f"{i:014d}" for i in range(1, 500)]
    day0 = date(2026, 9, 1)
    parts = [fp.sweep_slice(cnpjs, day0 + __import__("datetime").timedelta(days=k), 14) for k in range(14)]
    flat = [c for p in parts for c in p]
    assert sorted(flat) == cnpjs and len(flat) == len(set(flat))
    assert fp.sweep_slice(cnpjs, day0, 14) == parts[0]


async def test_daily_update_audits_register_and_fund_link_separately(monkeypatch):
    monkeypatch.setenv("FNET_DAILY_LOOKBACK_DAYS", "2")
    fake = _FakeFetcher({})
    ing, captured, up = _ingestor(fake)
    ing.registry_funds = lambda: []
    audits: List[str] = []

    async def fake_audited(client, entity, doc_type, fn, **kw):
        assert entity == "fnet"
        audits.append(doc_type)
        return await fn()

    with up, patch.object(fp, "audited", side_effect=fake_audited):
        out = await ing.daily_update()
    assert audits == ["register", "fund_link"]
    assert out == {fp.TABLE: 0, fp.FILTER_TABLE: 0}
    days = sorted({c[0] for c in fake.calls})
    assert len(days) == 2 and (days[1] - days[0]).days == 1


async def test_backfill_audits_one_row_per_calendar_month():
    fake = _FakeFetcher({})
    ing, _, up = _ingestor(fake)
    periods: List[tuple] = []

    async def fake_audited(client, entity, doc_type, fn, *, period_year=None, period_month=None, **kw):
        periods.append((period_year, period_month))
        return await fn()

    with up, patch.object(fp, "audited", side_effect=fake_audited):
        await ing.backfill(date(2026, 7, 30), date(2026, 9, 2))
    assert periods == [(2026, 7), (2026, 8), (2026, 9)]
    assert len({c[0] for c in fake.calls}) == 35   # every delivery day, once


async def test_backfill_continues_past_a_failed_month_then_raises():
    """One slow FNET month must not abandon the rest of the range, and must
    not be swallowed either: every month is attempted, the run still fails."""
    fake = _FakeFetcher({})
    ing, _, up = _ingestor(fake)
    attempted: List[tuple] = []

    async def fake_audited(client, entity, doc_type, fn, *, period_year=None, period_month=None, **kw):
        attempted.append((period_year, period_month))
        if (period_year, period_month) == (2026, 8):
            raise FnetFetchError("FNET dataInicial=01/08/2026 failed after 5 attempts: ReadTimeout('')")
        return await fn()

    with up, patch.object(fp, "audited", side_effect=fake_audited):
        with pytest.raises(fp.FnetBackfillIncomplete, match="2026-08"):
            await ing.backfill(date(2026, 7, 30), date(2026, 9, 2))
    assert attempted == [(2026, 7), (2026, 8), (2026, 9)]


def test_fetcher_default_timeout_covers_fnets_slow_answers(monkeypatch):
    monkeypatch.delenv("FNET_REQUEST_TIMEOUT", raising=False)
    assert FnetFetcher().timeout >= 150


# ---------------------------------------------------------------------------
# Schema: the migration is mirrored into schema.sql and locked from clients
# ---------------------------------------------------------------------------

def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", sql)).strip()


def test_migration_42_is_mirrored_into_schema_sql():
    mig = (ROOT / "src/store/migrations/42_fnet_document.sql").read_text(encoding="utf-8")
    schema = _norm((ROOT / "src/store/schema.sql").read_text(encoding="utf-8"))
    for stmt in _norm(mig).split(";"):
        if stmt.strip():
            assert stmt.strip() in schema, stmt[:80]


def test_fnet_tables_are_revoked_from_client_roles():
    grants = (ROOT / "src/store/analytical/12_grants_and_rls.sql").read_text(encoding="utf-8")
    assert "fnet_|" in grants
    for t in ("fnet_document", "fnet_document_filter"):
        assert re.search(rf"REVOKE ALL ON TABLE {t}\s+FROM anon, authenticated;", grants)


def test_fnet_backfill_needs_a_range_or_the_sweep():
    import argparse
    from src.pipeline import run_backfill as rb
    with pytest.raises(SystemExit, match="fnet-start"):
        import asyncio
        asyncio.run(rb.run_fnet(argparse.Namespace(fnet_start=None, fnet_end=None, fnet_sweep=False)))
