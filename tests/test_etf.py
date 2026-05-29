"""Tests for the ETF (Fundo de Índice) dataset: seed + enrichment ingest."""

import re
from unittest.mock import patch

from src.pipeline.ingest_etf import load_etf_seed, ingest_etf_registry


class TestEtfSeed:
    def test_seed_loads_with_required_columns(self):
        rows = load_etf_seed()
        assert rows, "seed CSV should not be empty"
        required = {"ticker", "cnpj", "fund_name", "provider", "underlying_index", "segment"}
        assert required.issubset(rows[0].keys())

    def test_seed_contains_known_etfs(self):
        tickers = {r["ticker"] for r in load_etf_seed()}
        # Anchor on the most liquid Brazilian equity ETF.
        assert "BOVA11" in tickers

    def test_seed_cnpjs_are_14_digits_and_unique(self):
        rows = load_etf_seed()
        cnpjs = [r["cnpj"] for r in rows]
        for c in cnpjs:
            assert re.fullmatch(r"\d{14}", c), f"bad CNPJ {c!r}"
        assert len(cnpjs) == len(set(cnpjs)), "duplicate CNPJ in seed"

    def test_seed_segments_are_known(self):
        allowed = {"equities_br", "equities_intl", "fixed_income", "crypto", "commodities"}
        assert {r["segment"] for r in load_etf_seed()} <= allowed


class TestEtfIngest:
    def _seed(self):
        return [{
            "ticker": "bova11",  # lower-case on purpose — should be upper-cased
            "cnpj": "10.406.511/0001-61",  # formatted — should be normalised
            "fund_name": "ISHARES IBOVESPA",
            "provider": "BlackRock (iShares)",
            "underlying_index": "Ibovespa",
            "segment": "equities_br",
        }]

    def test_ingest_normalises_and_enriches(self):
        cad_rows = [{
            "CNPJ_FUNDO": "10406511000161",
            "TAXA_ADM": "0,30",
            "TAXA_PERFM": "",
            "ADMIN": "BTG PACTUAL",
            "GESTOR": "BLACKROCK BRASIL",
            "SIT": "EM FUNCIONAMENTO NORMAL",
            "CLASSE_ANBIMA": "Ações Indexados",
            "DT_REG": "2008-09-01",
            "VL_PATRIM_LIQ": "1.234.567,89",
            "DT_PATRIM_LIQ": "2026-05-01",
        }]
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            captured["table"] = table
            captured["rows"] = rows
            captured["conflict"] = kw.get("conflict_columns")
            return len(rows)

        with patch("src.pipeline.ingest_etf.upsert_rows", side_effect=_fake_upsert):
            n = ingest_etf_registry(object(), self._seed(), cad_rows)

        assert n == 1
        assert captured["table"] == "cvm_etf_registry"
        assert captured["conflict"] == "ticker"
        rec = captured["rows"][0]
        assert rec["ticker"] == "BOVA11"
        assert rec["cnpj"] == "10406511000161"
        assert rec["taxa_adm"] == 0.30          # BR decimal comma parsed
        assert rec["taxa_perfm"] is None        # empty -> None
        assert rec["gestor"] == "BLACKROCK BRASIL"
        assert rec["vl_patrim_liq"] == 1234567.89
        assert rec["raw"]["underlying_index"] == "Ibovespa"

    def test_ingest_without_cad_rows_leaves_enrichment_null(self):
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            captured["rows"] = rows
            return len(rows)

        with patch("src.pipeline.ingest_etf.upsert_rows", side_effect=_fake_upsert):
            n = ingest_etf_registry(object(), self._seed(), cad_rows=None)

        assert n == 1
        rec = captured["rows"][0]
        assert rec["taxa_adm"] is None
        assert rec["situacao"] is None
        assert rec["cnpj"] == "10406511000161"  # still normalised from the seed

    def test_ingest_empty_seed_returns_zero(self):
        with patch("src.pipeline.ingest_etf.upsert_rows", side_effect=AssertionError("should not upsert")):
            assert ingest_etf_registry(object(), [], []) == 0

    def test_ingest_skips_rows_missing_ticker_or_cnpj(self):
        seed = [
            {"ticker": "", "cnpj": "10406511000161"},
            {"ticker": "X11", "cnpj": ""},
        ]
        with patch("src.pipeline.ingest_etf.upsert_rows", side_effect=AssertionError("should not upsert")):
            assert ingest_etf_registry(object(), seed, []) == 0
