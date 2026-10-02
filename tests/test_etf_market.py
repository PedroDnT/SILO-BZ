"""Tests for the ETF market-snapshot parser (etfsbrasil.com.br via Apify).

Covers the Brazilian-format scalar parsers and `_record_to_row` against a captured
`text` blob shaped like the scraper's `body.innerText`, plus the full
`ingest_etf_market` path with the Apify fetcher and DB upsert mocked out — so the
parser is protected by the offline pre-push suite even though the live scrape is
paid/rate-limited and never runs in tests.
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline import ingest_etf_market as m


# A slice of the /etfs/<ticker> rendered innerText, every figure label-then-value.
# This sample used to put NAV/cotistas/taxa value-then-label, matching the parser
# rather than the page, which is how a year sat in cotistas for every ETF unseen.
# The captured page shape is tests/fixtures/etfsbrasil/ (TestCapturedPage below).
SAMPLE_TEXT = """\
BOVA11
R$ 123,45
Patrimônio líquido (R$ MM)
1.234,56
Número de cotistas
45.678
Taxa de administração total
0,30 %
Nome do fundo
ISHARES IBOVESPA FUNDO DE ÍNDICE
Índice
Ibovespa
Provedor do índice
B3
Região
Brasil
Lançamento
01/09/2008
CNPJ
10.406.511/0001-61
ISIN
BRBOVACTF003
"""


class TestScalarParsers:
    def test_num_brazilian_format(self):
        assert m._num("1.234,56") == 1234.56
        assert m._num("0,30") == 0.30
        assert m._num("-46,93") == -46.93
        assert m._num("R$ 1.000.000,00") == 1_000_000.00

    def test_num_empty_and_placeholder_are_none(self):
        for v in (None, "", "-", "--", "n/a", "N/A", "ND", "—"):
            assert m._num(v) is None

    def test_pct_is_numeric(self):
        assert m._pct("4,91%") == 4.91

    def test_int_rounds(self):
        assert m._int("45.678") == 45678
        assert m._int(None) is None

    def test_date_ddmmyyyy(self):
        assert m._date("01/09/2008") == "2008-09-01"
        assert m._date("inválido") is None
        assert m._date("31/02/2020") is None  # impossible date → None, not a guess

    def test_ticker_normalises(self):
        assert m._ticker("bova11") == "BOVA11"
        assert m._ticker(" iVVB11 ") == "IVVB11"
        assert m._ticker("") is None

    def test_cnpj14_only_when_14_digits(self):
        assert m._cnpj14("10.406.511/0001-61") == "10406511000161"
        assert m._cnpj14("123") is None
        assert m._cnpj14(None) is None


class TestGrab:
    def test_grab_pulls_labelled_value(self):
        assert m._grab(SAMPLE_TEXT, m._RE["fund_name"]) == "ISHARES IBOVESPA FUNDO DE ÍNDICE"
        assert m._grab(SAMPLE_TEXT, m._RE["indice"]) == "Ibovespa"
        assert m._grab(SAMPLE_TEXT, m._RE["provedor"]) == "B3"

    def test_grab_none_on_empty_text(self):
        assert m._grab(None, m._RE["price"]) is None
        assert m._grab("", m._RE["price"]) is None


class TestRecordToRow:
    def test_full_record(self):
        rec = {"ticker": "bova11", "text": SAMPLE_TEXT, "source_url": "x"}
        row = m._record_to_row(rec, "2026-06-15")
        assert row is not None
        assert row["ticker"] == "BOVA11"
        assert row["snapshot_date"] == "2026-06-15"
        assert row["source"] == "etfsbrasil"
        assert row["price"] == 123.45
        # page shows R$ MM → stored in BRL (×1e6)
        assert row["nav"] == 1234.56 * 1_000_000
        assert row["cotistas"] == 45678
        assert row["taxa_adm_pct"] == 0.30
        assert row["fund_name"] == "ISHARES IBOVESPA FUNDO DE ÍNDICE"
        assert row["indice"] == "Ibovespa"
        assert row["provedor_indice"] == "B3"
        assert row["regiao"] == "Brasil"
        assert row["launch_date"] == "2008-09-01"
        assert row["cnpj"] == "10406511000161"
        assert row["isin"] == "BRBOVACTF003"
        # chart-rendered metrics stay NULL until mapped from next_data (never guessed)
        assert row["ret_12m_pct"] is None
        assert row["sharpe_12m"] is None

    def test_record_without_ticker_is_dropped(self):
        assert m._record_to_row({"ticker": "", "text": "x"}, "2026-06-15") is None
        assert m._record_to_row({"text": "x"}, "2026-06-15") is None

    def test_missing_fields_stay_none_not_zero(self):
        # A page that only carries a ticker must not fabricate NAV/price/cotistas.
        row = m._record_to_row({"ticker": "XPTO11", "text": "XPTO11\n"}, "2026-06-15")
        assert row is not None
        assert row["nav"] is None
        assert row["price"] is None
        assert row["cotistas"] is None


FIXTURES = Path(__file__).parent / "fixtures" / "etfsbrasil"


class TestCapturedPage:
    """The real page layout: labels in capitals ABOVE their values, and charts whose
    date range ("24 de set. de 2026") sits right above a second "Número de cotistas"
    / "Patrimônio líquido" label. Trimmed from the BOVA11 snapshot of 2026-09-26
    (etf_market_snapshot.raw->>'text'); the old value-then-label regexes read
    cotistas = 2026 and NAV = 2026 R$ MM from it."""

    TEXT = (FIXTURES / "bova11_innertext_20260926.txt").read_text(encoding="utf-8")

    def test_cotistas_is_the_holder_count_not_a_year(self):
        row = m._record_to_row({"ticker": "BOVA11", "text": self.TEXT}, "2026-09-26")
        assert row["cotistas"] == 105270

    def test_nav_and_fee_from_the_info_block(self):
        row = m._record_to_row({"ticker": "BOVA11", "text": self.TEXT}, "2026-09-26")
        assert row["nav"] == 14813.48 * 1_000_000
        assert row["taxa_adm_pct"] == 0.10
        assert row["price"] == 180.82
        assert row["cnpj"] == "10406511000161"
        assert row["isin"] == "BRBOVACTF003"

    def test_no_info_block_value_is_null_not_the_chart_axis(self):
        # 7 of 178 pages (BULZ11, BLOK11, ...) carry no figure under the labels:
        # the only "Número de Cotistas" line is the chart heading, then "Zoom",
        # then the date range and the year axis. That must stay NULL.
        text = self.TEXT
        text = text.replace("PATRIMÔNIO LÍQUIDO (R$ MM)\n14.813,48\n", "")
        text = text.replace("NÚMERO DE COTISTAS\n105.270\n", "")
        text = text.replace("TAXA DE ADMINISTRAÇÃO TOTAL\n0,10%\n", "")
        row = m._record_to_row({"ticker": "BULZ11", "text": text}, "2026-09-26")
        assert row["cotistas"] is None
        assert row["nav"] is None
        assert row["taxa_adm_pct"] is None

    def test_placeholder_value_is_null(self):
        text = self.TEXT.replace("NÚMERO DE COTISTAS\n105.270", "NÚMERO DE COTISTAS\n-")
        row = m._record_to_row({"ticker": "BOVA11", "text": text}, "2026-09-26")
        assert row["cotistas"] is None


def _only_log_rows(log):
    """An upsert fake that records audit rows and refuses any data write."""
    def _fake(conn, table, rows, **kw):
        assert table == "cvm_ingest_log", f"unexpected data write to {table}"
        log.append(rows[0])
        return len(rows)
    return _fake


class TestIngestEtfMarket:
    async def test_scrape_to_upsert(self, audit_log):
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            if table == "cvm_ingest_log":
                return len(rows)
            captured["table"] = table
            captured["rows"] = rows
            captured["conflict"] = kw.get("conflict_columns")
            return len(rows)

        records = [{"ticker": "bova11", "text": SAMPLE_TEXT}]

        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", return_value=records), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", side_effect=_fake_upsert):
            n = await m.ingest_etf_market(object(), tickers=["BOVA11"])

        assert n == 1
        assert captured["table"] == "etf_market_snapshot"
        assert captured["conflict"] == "ticker,snapshot_date"
        assert captured["rows"][0]["ticker"] == "BOVA11"
        # Rule 3: one audit row via ingest_log.audited — 'running' then 'ok'.
        assert len(audit_log.started) == 1
        assert audit_log.started[0]["entity"] == "etf_market"
        (fin,) = audit_log.finished
        assert (fin["status"], fin["rows"], fin["error"]) == ("ok", 1, None)

    async def test_records_without_ticker_raise(self, audit_log):
        # Scrape returned rows but none usable → must raise, never upsert nothing silently.
        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", return_value=[{"text": "no ticker"}]), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", return_value=0):
            with pytest.raises(RuntimeError, match="usable ticker"):
                await m.ingest_etf_market(object(), tickers=["BOVA11"])
        (fin,) = audit_log.finished
        assert fin["status"] == "error"
        assert "usable ticker" in fin["error"]

    async def test_no_tickers_raises(self, audit_log):
        # Empty explicit list falls through to the registry lookup; with no active
        # ETFs it must raise (seed the registry first), never run an empty scrape.
        with patch("src.pipeline.ingest_etf_market._active_tickers", return_value=[]), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", return_value=0):
            with pytest.raises(RuntimeError, match="No ETF tickers"):
                await m.ingest_etf_market(object(), tickers=[])
        (fin,) = audit_log.finished
        assert fin["status"] == "error"

    async def test_apify_unavailable_is_logged_skipped(self, audit_log, caplog):
        """ApifyScrapeUnavailableError → skipped audit row, returns 0, does not raise.

        run_daily no longer checks for this error class; ingest_etf_market absorbs
        it as Outcome(0, "skipped"), logs loudly, and returns 0 so ANALYZE and
        analytics still run on usage-limit days.
        """
        boom = m.ApifyScrapeUnavailableError("403 usage hard limit")
        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", side_effect=boom), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", return_value=0), \
             caplog.at_level(logging.ERROR, logger="src.pipeline.ingest_etf_market"):
            n = await m.ingest_etf_market(object(), tickers=["BOVA11"])
        assert n == 0
        (fin,) = audit_log.finished
        assert fin["status"] == "skipped"
        assert "403 usage hard limit" in fin["error"]
        assert fin["rows"] == 0
        assert "did not return a dataset" in caplog.text

    @pytest.mark.parametrize("exc_cls,msg", [
        ("ApifyActorNotApprovedError",
         "approve at https://console.apify.com/actors/moJRLRc85AitArpNN"),
        ("ApifyRunTimeoutError",
         "HTTP 408 run-timeout-exceeded: Actor run exceeded the timeout"),
        ("ApifyRunAbortedError",
         "run d2UCTxohVY9IcQX9a was aborted (status=ABORTED) — no dataset"),
        ("ApifyUsageLimitError",
         "account usage limit exceeded (HTTP 403 platform-feature-disabled)"),
    ])
    async def test_apify_error_variants_are_skipped(self, exc_cls, msg, audit_log):
        """All ApifyScrapeUnavailableError subclasses → skipped, not error."""
        from src.fetchers import apify_etf_fetcher as aef
        boom = getattr(aef, exc_cls)(msg)
        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", side_effect=boom), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", return_value=0):
            n = await m.ingest_etf_market(object(), tickers=["BOVA11"])
        assert n == 0
        (fin,) = audit_log.finished
        assert fin["status"] == "skipped"

    async def test_a_failed_audit_write_does_not_mask_the_ingest(self):
        def _fake_upsert(conn, table, rows, **kw):
            if table == "cvm_ingest_log":
                raise RuntimeError("audit table unavailable")
            return len(rows)

        records = [{"ticker": "bova11", "text": SAMPLE_TEXT}]
        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", return_value=records), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", side_effect=_fake_upsert):
            assert await m.ingest_etf_market(object(), tickers=["BOVA11"]) == 1
