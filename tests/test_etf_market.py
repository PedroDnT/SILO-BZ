"""Tests for the ETF market-snapshot parser (etfsbrasil.com.br via Apify).

Covers the Brazilian-format scalar parsers and `_record_to_row` against a captured
`text` blob shaped like the scraper's `body.innerText`, plus the full
`ingest_etf_market` path with the Apify fetcher and DB upsert mocked out — so the
parser is protected by the offline pre-push suite even though the live scrape is
paid/rate-limited and never runs in tests.
"""

from unittest.mock import patch

from src.pipeline import ingest_etf_market as m


# A realistic slice of the /etfs/<ticker> rendered innerText: values appear next to
# their Portuguese labels exactly as the _RE patterns expect (value-then-label for
# NAV/cotistas/taxa, label-then-value for name/index/região/lançamento/CNPJ/ISIN).
SAMPLE_TEXT = """\
BOVA11
R$ 123,45
1.234,56
Patrimônio líquido
45.678
Número de cotistas
0,30 %
Taxa de administração total
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


class TestIngestEtfMarket:
    def test_scrape_to_upsert(self):
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            captured["table"] = table
            captured["rows"] = rows
            captured["conflict"] = kw.get("conflict_columns")
            return len(rows)

        records = [{"ticker": "bova11", "text": SAMPLE_TEXT}]

        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", return_value=records), \
             patch("src.pipeline.ingest_etf_market.upsert_rows", side_effect=_fake_upsert):
            n = m.ingest_etf_market(object(), tickers=["BOVA11"])

        assert n == 1
        assert captured["table"] == "etf_market_snapshot"
        assert captured["conflict"] == "ticker,snapshot_date"
        assert captured["rows"][0]["ticker"] == "BOVA11"

    def test_records_without_ticker_raise(self):
        # Scrape returned rows but none usable → must raise, never upsert nothing silently.
        with patch.object(m.ApifyETFFetcher, "__init__", return_value=None), \
             patch.object(m.ApifyETFFetcher, "fetch", return_value=[{"text": "no ticker"}]), \
             patch("src.pipeline.ingest_etf_market.upsert_rows",
                   side_effect=AssertionError("should not upsert")):
            try:
                m.ingest_etf_market(object(), tickers=["BOVA11"])
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "usable ticker" in str(exc)

    def test_no_tickers_raises(self):
        # Empty explicit list falls through to the registry lookup; with no active
        # ETFs it must raise (seed the registry first), never run an empty scrape.
        with patch("src.pipeline.ingest_etf_market._active_tickers", return_value=[]):
            try:
                m.ingest_etf_market(object(), tickers=[])
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "No ETF tickers" in str(exc)
