"""Tests for the ETF (Fundo de Índice) dataset: seed + enrichment ingest."""

import re
from unittest.mock import patch

from src.parsers.mapping import derive_is_active
from src.pipeline.ingest_etf import load_etf_seed, ingest_etf_registry


class TestDeriveIsActive:
    def test_operating_statuses_are_active(self):
        for s in ("Em Funcionamento Normal", "EM FUNCIONAMENTO NORMAL", "ATIVO"):
            assert derive_is_active(s) is True

    def test_discontinued_statuses_are_inactive(self):
        for s in ("CANCELADA", "Liquidação", "INCORPORAÇÃO", "Fase Pré-Operacional"):
            assert derive_is_active(s) is False

    def test_missing_status_is_none(self):
        assert derive_is_active(None) is None
        assert derive_is_active("") is None
        assert derive_is_active("   ") is None


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

    def test_seed_cnpjs_are_14_digits_and_tickers_unique(self):
        rows = load_etf_seed()
        for c in (r["cnpj"] for r in rows):
            assert re.fullmatch(r"\d{14}", c), f"bad CNPJ {c!r}"
        # ticker is the registry primary key and must be unique. CNPJ is NOT
        # unique: Investo umbrella funds list several distinct ETF tickers (e.g.
        # FOOD11 / GLDX11) under one fund CNPJ, so the join key can repeat.
        tickers = [r["ticker"] for r in rows]
        assert len(tickers) == len(set(tickers)), "duplicate ticker in seed"

    def test_seed_segments_are_known(self):
        allowed = {
            "equities_br", "equities_intl", "fixed_income_br", "fixed_income_intl",
            "crypto", "commodities", "multi_asset", "real_estate",
        }
        assert {r["segment"] for r in load_etf_seed()} <= allowed

    def test_seed_carries_lifecycle_columns(self):
        rows = load_etf_seed()
        assert {"situacao", "is_active", "dt_cancel"}.issubset(rows[0].keys())


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
        assert rec["situacao"] == "EM FUNCIONAMENTO NORMAL"
        assert rec["is_active"] is True
        assert rec["dt_cancel"] is None

    def test_ingest_marks_discontinued_etf(self):
        cad_rows = [{
            "CNPJ_FUNDO": "10406511000161",
            "SIT": "CANCELADA",
            "DT_CANCEL": "2022-03-15",
        }]
        captured = {}

        def _fake_upsert(conn, table, rows, **kw):
            captured["rows"] = rows
            return len(rows)

        with patch("src.pipeline.ingest_etf.upsert_rows", side_effect=_fake_upsert):
            ingest_etf_registry(object(), self._seed(), cad_rows)

        rec = captured["rows"][0]
        assert rec["is_active"] is False
        assert str(rec["dt_cancel"]) == "2022-03-15"   # discontinued ETF retained

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
