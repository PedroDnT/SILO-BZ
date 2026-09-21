"""The SGS history load: ten-year windows, the inflation series set, and
running one BACEN source without the others.

SGS refuses a window longer than ten years on a DAILY series — verified
2026-09-21, series 11 (SELIC diária) asked for 1980..2026 answers HTTP 406
"O sistema aceita uma janela de consulta de, no máximo, 10 anos em séries de
periodicidade diária". Monthly series accept the full window. The fetcher does
not know a series' periodicity, so every window is sliced; without that a
1980 backfill for IPCA takes SELIC and CDI down with it and the whole SGS
source raises.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, List
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.fetchers.bacen_fetcher import BacenClient, BacenFetchError, _sgs_windows
from src.pipeline.bacen_pipeline import (
    INFLATION_SERIES, SGS_SERIES, BacenIngestor,
)
from src.pipeline.run_backfill import parse_bacen_sources


# ---------------------------------------------------------------------------
# Window slicing
# ---------------------------------------------------------------------------

def test_a_window_inside_five_years_is_one_request():
    assert _sgs_windows("2022-01-01", "2026-09-21") == [("2022-01-01", "2026-09-21")]
    assert _sgs_windows("2026-08-22", "2026-09-21") == [("2026-08-22", "2026-09-21")], "the daily window"


def test_the_1980_history_is_cut_into_five_year_slices_that_do_not_overlap():
    """Five, not ten: series 432 (SELIC meta, one row per calendar day)
    answered 2010-01-01..2019-12-31 with HTTP 200 {"erro":{}} three times
    running on 2026-09-21 (Backfill run 35651030075), and both five-year
    halves with their rows."""
    windows = _sgs_windows("1980-01-01", "2026-09-21")
    assert windows == [
        ("1980-01-01", "1984-12-31"),
        ("1985-01-01", "1989-12-31"),
        ("1990-01-01", "1994-12-31"),
        ("1995-01-01", "1999-12-31"),
        ("2000-01-01", "2004-12-31"),
        ("2005-01-01", "2009-12-31"),
        ("2010-01-01", "2014-12-31"),
        ("2015-01-01", "2019-12-31"),
        ("2020-01-01", "2024-12-31"),
        ("2025-01-01", "2026-09-21"),
    ]
    # Contiguous and non-overlapping: every slice starts the day after the last.
    from datetime import date, timedelta
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert date.fromisoformat(next_start) == date.fromisoformat(prev_end) + timedelta(days=1)


def test_a_slice_never_reaches_the_same_calendar_day_n_years_later():
    """The ten-year rule counts 2010-01-01..2020-01-01 as over the limit; the
    same off-by-one applies to the five-year slices."""
    assert _sgs_windows("2010-01-01", "2015-01-01") == [
        ("2010-01-01", "2014-12-31"), ("2015-01-01", "2015-01-01"),
    ]


def test_open_ended_windows_are_left_alone():
    assert _sgs_windows(None, "2026-01-01") == [(None, "2026-01-01")]
    assert _sgs_windows("1980-01-01", None) == [("1980-01-01", None)]


def _client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


@pytest.mark.asyncio
async def test_a_long_window_issues_one_request_per_slice_and_unions_them(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "1")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")
    calls: List[Dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        calls.append(q)
        # One observation per slice, dated at the slice start.
        d, m, y = q["dataInicial"].split("/")
        return httpx.Response(200, json=[{"data": f"01/01/{y}", "valor": "1.0"}])

    with patch("httpx.AsyncClient", _client_factory(handler)):
        rows = await BacenClient().get_sgs_series(
            {"IPCA": 433}, start="1980-01-01", end="2026-09-21",
        )
    assert [c["dataInicial"] for c in calls] == [
        "01/01/1980", "01/01/1985", "01/01/1990", "01/01/1995", "01/01/2000",
        "01/01/2005", "01/01/2010", "01/01/2015", "01/01/2020", "01/01/2025",
    ]
    assert calls[-1]["dataFinal"] == "21/09/2026" and calls[0]["dataFinal"] == "31/12/1984"
    assert [r["date"] for r in rows] == [
        f"{y}-01-01" for y in (1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025)
    ]


@pytest.mark.asyncio
async def test_a_200_with_bacens_empty_error_envelope_raises_with_the_body(monkeypatch):
    """Measured 2026-09-21 on series 432, 2010-01-01..2019-12-31: HTTP 200,
    body {"erro":{}}, every time. Not a list, so never rows; the message must
    carry the body, because 'got dict' alone cost a run to decode."""
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "1")
    monkeypatch.setenv("BACEN_OLINDA_RETRY_DELAY", "0")
    with patch("httpx.AsyncClient", _client_factory(lambda r: httpx.Response(200, json={"erro": {}}))):
        with pytest.raises(BacenFetchError, match=r'expected a JSON list, got dict: \{"erro"'):
            await BacenClient().get_sgs_series({"SELIC_META": 432}, start="2010-01-01", end="2014-12-31")


@pytest.mark.asyncio
async def test_the_ultimos_path_is_never_sliced(monkeypatch):
    monkeypatch.setenv("BACEN_OLINDA_MAX_RETRIES", "1")
    n = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["calls"] += 1
        return httpx.Response(200, json=[{"data": "01/08/2026", "valor": "-0.32"}])

    with patch("httpx.AsyncClient", _client_factory(handler)):
        await BacenClient().get_sgs_series({"IPCA": 433}, last=1)
    assert n["calls"] == 1


# ---------------------------------------------------------------------------
# The inflation series set
# ---------------------------------------------------------------------------

def test_every_inflation_series_is_fetched_by_the_pipeline():
    for label, (code, family, unit, name) in INFLATION_SERIES.items():
        assert SGS_SERIES[label] == code, label
        assert family in {"headline", "core", "classification", "diffusion", "group"}, label
        assert unit in {"pct_month", "pct_12m", "pct_items"}, label
        assert name.startswith("IPCA"), label
    assert len(set(SGS_SERIES.values())) == len(SGS_SERIES)


def test_the_group_codes_carry_the_measured_not_the_intuitive_order():
    """1640..1643 are NOT IBGE groups 6..9 in order — matched value for value
    against SIDRA 7060 on 2026-06, -07 and -08 (1640: -0.09 = Comunicação,
    1641: 0.23 = Saúde, 1642: 1.30 = Despesas pessoais, 1643: 0.47 = Educação
    in 2026-08)."""
    assert INFLATION_SERIES["IPCA_G_COMUNICACAO"][0] == 1640
    assert INFLATION_SERIES["IPCA_G_SAUDE"][0] == 1641
    assert INFLATION_SERIES["IPCA_G_DESPESAS_PESSOAIS"][0] == 1642
    assert INFLATION_SERIES["IPCA_G_EDUCACAO"][0] == 1643
    groups = {k: v[0] for k, v in INFLATION_SERIES.items() if v[1] == "group"}
    assert len(groups) == 9 and sorted(groups.values()) == list(range(1635, 1644))


def test_the_twelve_month_series_is_bacens_own_not_a_chain():
    code, family, unit, _ = INFLATION_SERIES["IPCA_12M"]
    assert (code, family, unit) == (13522, "headline", "pct_12m")


# ---------------------------------------------------------------------------
# Running one source
# ---------------------------------------------------------------------------

def _ingestor() -> BacenIngestor:
    with patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()):
        return BacenIngestor()


def test_sources_can_be_narrowed_to_sgs_only():
    ing = _ingestor()
    assert [s[0] for s in ing._sources("2019-01-01", "2026-01-01")] == ["sgs", "ptax", "expectativas"]
    assert [s[0] for s in ing._sources("2019-01-01", "2026-01-01", ["sgs"])] == ["sgs"]
    assert [s[0] for s in ing._sources("2019-01-01", "2026-01-01", ["ptax", "sgs"])] == ["sgs", "ptax"]


def test_an_unknown_source_raises_rather_than_running_nothing():
    ing = _ingestor()
    with pytest.raises(ValueError, match="unknown BACEN source"):
        ing._sources("2019-01-01", "2026-01-01", ["focus"])
    with pytest.raises(ValueError):
        ing._sources("2019-01-01", "2026-01-01", [])


@pytest.mark.asyncio
async def test_backfill_with_sources_runs_only_those_under_audit():
    ing = _ingestor()
    ran: List[str] = []

    async def fake_sgs(start, end):
        ran.append("sgs"); return 7

    async def fake_ptax(start, end):
        ran.append("ptax"); return 1

    async def fake_exp(start):
        ran.append("expectativas"); return 1

    async def fake_audited(client, entity, doc_type, fn, **kw):
        return await fn()

    with patch.object(ing, "ingest_sgs", fake_sgs), \
         patch.object(ing, "ingest_ptax", fake_ptax), \
         patch.object(ing, "ingest_expectativas", fake_exp), \
         patch("src.pipeline.bacen_pipeline.audited", fake_audited):
        totals = await ing.backfill(start="1980-01-01", sources=["sgs"])
    assert ran == ["sgs"]
    assert totals == {"bacen_sgs": 7}


def test_cli_parses_the_sources_list():
    assert parse_bacen_sources(None) is None
    assert parse_bacen_sources("sgs") == ["sgs"]
    assert parse_bacen_sources(" sgs, ptax ") == ["sgs", "ptax"]
    with pytest.raises(SystemExit):
        parse_bacen_sources("")
