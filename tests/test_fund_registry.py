"""Tests for the CVM-175 unified fund registry ingest + entity-type derivation."""

from unittest.mock import patch

from src.pipeline.ingest_misc import _entity_from_tipo, ingest_fund_registry_cvm175


class TestEntityFromTipo:
    def test_short_codes(self):
        cases = {
            "FI": "fi", "FIF": "fi", "FACFIF": "fi", "FAPI": "fi", "FITVM": "fi",
            "FIDC": "fidc",
            "FII": "fii", "FIIM": "fii",
            "FIP": "fip", "FMIEE": "fip", "FMIA-CL": "fip",
            "FIAGRO": "fiagro",
            "FUNCINE": "other", "FICART": "other", "FMP-FGTS": "other",
        }
        for tipo, expected in cases.items():
            assert _entity_from_tipo(tipo) == expected, tipo

    def test_verbose_registro_classe_labels(self):
        assert _entity_from_tipo("Classes de Cotas de Fundos FIF") == "fi"
        assert _entity_from_tipo("Classes de Cotas de Fundos FII") == "fii"
        assert _entity_from_tipo("Classes de Cotas de Fundos FIDC") == "fidc"
        assert _entity_from_tipo("Classes de Cotas de Fundos FIP (FMIEE)") == "fip"
        assert _entity_from_tipo("Classes de Cotas de Fundos FIAGRO") == "fiagro"

    def test_empty_defaults_to_fi(self):
        assert _entity_from_tipo("") == "fi"
        assert _entity_from_tipo(None) == "fi"


class TestIngestCvm175:
    def test_derives_entity_status_and_retains_cancelled(self):
        rows = [
            {  # active FIDC class
                "CNPJ_Fundo": "11.222.333/0001-44",
                "Denominacao_Social": "ALPHA FIDC",
                "Tipo_Fundo": "FIDC",
                "Situacao": "Em Funcionamento Normal",
                "Data_Registro": "2021-05-10",
            },
            {  # cancelled FII — retained, flagged inactive, cancel date kept
                "CNPJ_Fundo": "55.666.777/0001-88",
                "Denominacao_Social": "BETA FII",
                "Tipo_Fundo": "FII",
                "Situacao": "Cancelado",
                "Data_Cancelamento": "2020-09-30",
            },
            {  # missing CNPJ -> skipped
                "CNPJ_Fundo": "",
                "Denominacao_Social": "NO CNPJ",
                "Tipo_Fundo": "FI",
            },
        ]
        captured = {}

        def _fake_upsert(conn, table, recs, **kw):
            captured["table"] = table
            captured["recs"] = recs
            captured["conflict"] = kw.get("conflict_columns")
            return len(recs)

        with patch("src.pipeline.ingest_misc.upsert_rows", side_effect=_fake_upsert):
            n = ingest_fund_registry_cvm175(object(), rows)

        assert n == 2  # third row skipped
        assert captured["table"] == "cvm_fund_registry"
        assert captured["conflict"] == "cnpj,entity_type"
        by_name = {r["fund_name"]: r for r in captured["recs"]}

        alpha = by_name["ALPHA FIDC"]
        assert alpha["entity_type"] == "fidc"
        assert alpha["is_active"] is True
        assert alpha["cnpj"] == "11222333000144"

        beta = by_name["BETA FII"]
        assert beta["entity_type"] == "fii"
        assert beta["is_active"] is False
        assert str(beta["dt_cancel"]) == "2020-09-30"

    def test_empty_returns_zero(self):
        with patch("src.pipeline.ingest_misc.upsert_rows", side_effect=AssertionError("no upsert")):
            assert ingest_fund_registry_cvm175(object(), []) == 0
