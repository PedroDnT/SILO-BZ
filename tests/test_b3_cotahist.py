"""Offline tests for B3 COTAHIST parse + ingest.

HTTP and Postgres are mocked. The 245-byte layout was checked against the
live 2026-08-13 daily file (PETR4 close 41.90, ISIN BRPETRACNPR6).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.fetchers.b3_fetcher import (
    B3CotahistFetchError,
    B3CotahistFetcher,
    B3CotahistNotFound,
    daily_filename,
    yearly_filename,
)
from src.parsers.cotahist import (
    CotahistParseError,
    parse_cotahist_bytes,
    parse_quote_line,
)
from src.pipeline.b3_pipeline import B3Ingestor


def _put(buf: list[str], start: int, end: int, val: str, *, align: str = "left") -> None:
    width = end - start + 1
    s = str(val)
    if align == "right":
        s = s.rjust(width)
    else:
        s = s.ljust(width)
    s = s[:width]
    buf[start - 1 : end] = list(s)


def _n(value: float, width: int, decimals: int = 2) -> str:
    scaled = int(round(value * (10 ** decimals)))
    return str(scaled).zfill(width)


def make_quote_line(
    *,
    ticker: str = "PETR4",
    trade_date: str = "20260813",
    tpmerc: str = "010",
    codbdi: str = "02",
    prazot: str = "",
    nome: str = "PETROBRAS",
    especi: str = "PN",
    moeda: str = "R$",
    open_: float = 41.50,
    high: float = 42.00,
    low: float = 41.20,
    avg: float = 41.70,
    close: float = 41.90,
    bid: float = 41.89,
    ask: float = 41.91,
    trades: int = 46835,
    qty: int = 1000,
    volume: float = 1546454687.00,
    isin: str = "BRPETRACNPR6",
    expiry: str = "99991231",
    factor: int = 1,
) -> str:
    buf = [" "] * 245
    _put(buf, 1, 2, "01")
    _put(buf, 3, 10, trade_date)
    _put(buf, 11, 12, codbdi)
    _put(buf, 13, 24, ticker)
    _put(buf, 25, 27, tpmerc)
    _put(buf, 28, 39, nome)
    _put(buf, 40, 49, especi)
    _put(buf, 50, 52, prazot)
    _put(buf, 53, 56, moeda)
    _put(buf, 57, 69, _n(open_, 13), align="right")
    _put(buf, 70, 82, _n(high, 13), align="right")
    _put(buf, 83, 95, _n(low, 13), align="right")
    _put(buf, 96, 108, _n(avg, 13), align="right")
    _put(buf, 109, 121, _n(close, 13), align="right")
    _put(buf, 122, 134, _n(bid, 13), align="right")
    _put(buf, 135, 147, _n(ask, 13), align="right")
    _put(buf, 148, 152, str(trades).zfill(5), align="right")
    _put(buf, 153, 170, str(qty).zfill(18), align="right")
    _put(buf, 171, 188, _n(volume, 18), align="right")
    _put(buf, 189, 201, _n(0, 13), align="right")
    _put(buf, 202, 202, "0")
    _put(buf, 203, 210, expiry)
    _put(buf, 211, 217, str(factor).zfill(7), align="right")
    _put(buf, 231, 242, isin)
    _put(buf, 243, 245, "000")
    line = "".join(buf)
    assert len(line) == 245
    return line


def make_header(year: int = 2026, generated: str = "20260813") -> str:
    buf = [" "] * 245
    _put(buf, 1, 2, "00")
    _put(buf, 3, 15, "COTAHIST.2026")
    _put(buf, 16, 23, "BOVESPA")
    _put(buf, 24, 31, generated)
    return "".join(buf)


def make_trailer(n: int = 4, generated: str = "20260813") -> str:
    buf = [" "] * 245
    _put(buf, 1, 2, "99")
    _put(buf, 3, 15, "COTAHIST.2026")
    _put(buf, 16, 23, "BOVESPA")
    _put(buf, 24, 31, generated)
    _put(buf, 32, 42, str(n).zfill(11), align="right")
    return "".join(buf)


def make_txt(*quotes: str) -> str:
    return "\n".join([make_header(), *quotes, make_trailer(len(quotes) + 2)]) + "\n"


def make_zip(txt: str, name: str = "COTAHIST_D13082026.TXT") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, txt.encode("latin-1"))
    return buf.getvalue()


class TestLayoutRoundtrip:
    def test_petr4_close_matches_live_sample(self):
        # Live 2026-08-13 file: PREULT 0000000004190 → 41.90
        line = make_quote_line(close=41.90, isin="BRPETRACNPR6")
        row = parse_quote_line(line)
        assert row is not None
        assert row["codneg"] == "PETR4"
        assert row["trade_date"] == "2026-08-13"
        assert row["tpmerc"] == "010"
        assert row["codbdi"] == "02"
        assert row["prazot"] == ""
        assert row["preco_fechamento"] == pytest.approx(41.90)
        assert row["isin"] == "BRPETRACNPR6"
        assert row["data_vencimento"] is None  # 99991231 sentinel
        assert row["source"] == "b3_cotahist"

    def test_live_petr4_line_from_b3_file(self):
        assert len(LIVE_PETR4_20260813) == 245
        row = parse_quote_line(LIVE_PETR4_20260813)
        assert row["codneg"] == "PETR4"
        assert row["trade_date"] == "2026-08-13"
        assert row["preco_fechamento"] == pytest.approx(41.90)
        assert row["preco_abertura"] == pytest.approx(41.15)
        assert row["negocios"] == 46835
        assert row["volume"] == pytest.approx(1_546_454_687.00)
        assert row["isin"] == "BRPETRACNPR6"
        assert row["quantidade"] == 37_063_800

    def test_header_and_trailer_are_dropped(self):
        assert parse_quote_line(make_header()) is None
        assert parse_quote_line(make_trailer()) is None

    def test_short_line_dropped(self):
        assert parse_quote_line("01PETR4") is None

    def test_empty_ticker_dropped(self):
        line = make_quote_line(ticker="")
        assert parse_quote_line(line) is None

    def test_bad_date_dropped_not_guessed(self):
        line = make_quote_line(trade_date="20261399")
        assert parse_quote_line(line) is None

    def test_unreadable_close_dropped_not_zero(self):
        buf = list(make_quote_line())
        buf[108:121] = list("             ")
        assert parse_quote_line("".join(buf)) is None

    def test_fracionario_and_prazot_kept(self):
        line = make_quote_line(ticker="PETR4F", tpmerc="020", codbdi="96", prazot="030")
        row = parse_quote_line(line)
        assert row["codneg"] == "PETR4F"
        assert row["tpmerc"] == "020"
        assert row["prazot"] == "030"

    def test_zip_roundtrip_skips_non_quotes(self):
        txt = make_txt(
            make_quote_line(ticker="PETR4", close=41.90),
            make_quote_line(ticker="VALE3", close=60.12, isin="BRVALEACNOR0"),
        )
        rows = parse_cotahist_bytes(make_zip(txt), origin="fixture")
        assert [r["codneg"] for r in rows] == ["PETR4", "VALE3"]
        assert rows[1]["preco_fechamento"] == pytest.approx(60.12)

    def test_empty_zip_raises(self):
        txt = make_txt()  # header + trailer only
        with pytest.raises(CotahistParseError, match="no register-01"):
            parse_cotahist_bytes(make_zip(txt), origin="empty")

    def test_zip_without_txt_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.md", b"nope")
        with pytest.raises(CotahistParseError, match="no .TXT"):
            parse_cotahist_bytes(buf.getvalue())


LIVE_PETR4_20260813 = (
    "012026081302PETR4       010PETROBRAS   PN      N2   R$  "
    "0000000004115000000000419600000000041070000000004172"
    "000000000419000000000041860000000004190468350000000000370638"
    "00000000154645468700000000000000009999123100000010000000000000"
    "BRPETRACNPR6229"
)


def _client_factory(handler):
    transport = httpx.MockTransport(handler)
    orig = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    return factory


class TestFetcher:
    def test_filenames(self):
        assert daily_filename(date(2026, 8, 13)) == "COTAHIST_D13082026.ZIP"
        assert yearly_filename(2025) == "COTAHIST_A2025.ZIP"

    @pytest.mark.asyncio
    async def test_404_is_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        fetcher = B3CotahistFetcher(max_retries=1, timeout=5)
        with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
            with pytest.raises(B3CotahistNotFound, match="Data not found"):
                await fetcher.fetch_daily(date(2026, 8, 8))

    @pytest.mark.asyncio
    async def test_http_500_raises_after_retries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        fetcher = B3CotahistFetcher(max_retries=2, retry_delay=0, timeout=5)
        with patch("httpx.AsyncClient", side_effect=_client_factory(handler)):
            with pytest.raises(B3CotahistFetchError, match="after 2 attempts"):
                await fetcher.fetch_year(2025)


class TestIngestor:
    @pytest.mark.asyncio
    async def test_ingest_daily_upserts_conflict_key(self):
        txt = make_txt(make_quote_line(ticker="PETR4", close=41.90))
        payload = make_zip(txt)

        with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.b3_pipeline.upsert_rows") as up:
            up.return_value = 1
            ing = B3Ingestor(fetcher=MagicMock())
            ing._fetcher.fetch_daily = AsyncMock(return_value=payload)
            n = await ing.ingest_daily(date(2026, 8, 13))

        assert n == 1
        quote_calls = [c for c in up.call_args_list if c.args[1] == "b3_cotahist"]
        assert quote_calls
        args, kwargs = quote_calls[0]
        assert kwargs["conflict_columns"] == "codneg,trade_date,tpmerc,codbdi,prazot"
        row = args[2][0]
        assert row["codneg"] == "PETR4"
        assert row["preco_fechamento"] == pytest.approx(41.90)

    @pytest.mark.asyncio
    async def test_404_is_skipped_not_raised(self):
        with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.b3_pipeline.upsert_rows", return_value=1):
            ing = B3Ingestor(fetcher=MagicMock())
            ing._fetcher.fetch_daily = AsyncMock(
                side_effect=B3CotahistNotFound("Data not found at x")
            )
            n = await ing.ingest_daily(date(2026, 8, 8))
        assert n == 0

    @pytest.mark.asyncio
    async def test_fetch_error_raises(self):
        with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.b3_pipeline.upsert_rows", return_value=1):
            ing = B3Ingestor(fetcher=MagicMock())
            ing._fetcher.fetch_daily = AsyncMock(
                side_effect=B3CotahistFetchError("HTTP 500")
            )
            with pytest.raises(B3CotahistFetchError):
                await ing.ingest_daily(date(2026, 8, 13))

    @pytest.mark.asyncio
    async def test_empty_parse_raises_not_silent_zero(self):
        with patch("src.pipeline.b3_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.b3_pipeline.upsert_rows", return_value=1):
            ing = B3Ingestor(fetcher=MagicMock())
            ing._fetcher.fetch_daily = AsyncMock(return_value=make_zip(make_txt()))
            with pytest.raises(CotahistParseError):
                await ing.ingest_daily(date(2026, 8, 13))


class TestServeSchema:
    """Landing DDL must keep the cash-market serve path (partial index + view)."""

    def test_schema_has_vista_covering_index_and_view(self):
        from pathlib import Path

        schema = Path("src/store/schema.sql").read_text(encoding="utf-8")
        assert "idx_b3_cotahist_vista" in schema
        assert "WHERE tpmerc = '010'" in schema
        assert "CREATE OR REPLACE VIEW vw_b3_quote_vista" in schema
        assert "codbdi" in schema
        assert "idx_b3_cotahist_codneg" not in schema

    def test_api_contract_defines_quotes(self):
        from pathlib import Path

        sql = Path("src/store/analytical/19_api_contract.sql").read_text(
            encoding="utf-8"
        )
        assert "CREATE OR REPLACE VIEW api.quotes" in sql
        assert "api.quote_latest" in sql
        assert "api.panel" in sql
        assert "REVOKE ALL ON FUNCTION api.quote_latest" in sql

    def test_migration_19_drops_redundant_codneg_index(self):
        from pathlib import Path

        mig = Path("src/store/migrations/19_b3_cotahist_serve.sql").read_text(
            encoding="utf-8"
        )
        assert "DROP INDEX IF EXISTS idx_b3_cotahist_codneg" in mig
        assert "idx_b3_cotahist_vista" in mig
        assert "vw_b3_quote_vista" in mig
