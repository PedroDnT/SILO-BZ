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


class TestClassRowsDoNotErasePublishedFundFields:
    """registro_classe must not overwrite the manager registro_fundo published.

    CVM reuses the fund's CNPJ for its classes (36,492 of 36,606 CNPJ_Classe
    values are also a CNPJ_Fundo, measured 2026-08-28), and both files upsert
    into cvm_fund_registry on (cnpj, entity_type). registro_classe.csv has no
    Administrador and no Gestor column at all, so it used to map them to None
    and blank the manager for 36,343 funds on every run.
    """

    # Real registro_classe.csv header (2026-08-28), trimmed to what matters.
    CLASSE_ROW = {
        "ID_Registro_Fundo": "7779",
        "ID_Registro_Classe": "36019",
        "CNPJ_Classe": "38.542.889/0001-01",
        "Tipo_Classe": "Classes de Cotas de Fundos FIIM",
        "Denominacao_Social": "TREND ETF BLOOMBERG ALL COUNTRIES CLASSE DE ÍNDICE",
        "Situacao": "Em Funcionamento Normal",
        "Patrimonio_Liquido": "356592737,05",
        "Data_Patrimonio_Liquido": "2026-08-25",
        "Custodiante": "BANCO BNP PARIBAS BRASIL S/A",
    }

    def _capture(self, rows):
        captured = {}

        def _fake_upsert(conn, table, recs, **kw):
            captured["recs"] = recs
            return len(recs)

        with patch("src.pipeline.ingest_misc.upsert_rows", side_effect=_fake_upsert):
            ingest_fund_registry_cvm175(object(), rows)
        return captured["recs"]

    def test_manager_columns_absent_from_the_upsert(self):
        rec = self._capture([dict(self.CLASSE_ROW)])[0]
        # Absent, not None: a column that is not in the record is in neither the
        # INSERT list nor the ON CONFLICT SET, so the fund's value survives.
        for col in ("gestor_name", "gestor_id", "admin_name", "admin_cnpj"):
            assert col not in rec, f"{col} must not be written by registro_classe"

    def test_columns_the_class_file_does_publish_are_still_written(self):
        rec = self._capture([dict(self.CLASSE_ROW)])[0]
        assert rec["cnpj"] == "38542889000101"
        assert rec["entity_type"] == "fii"
        assert rec["fund_name"].startswith("TREND ETF BLOOMBERG")
        assert rec["vl_patrim_liq"] == 356592737.05
        assert str(rec["dt_patrim_liq"]) == "2026-08-25"

    def test_fundo_file_still_writes_the_manager(self):
        fundo_row = {
            "ID_Registro_Fundo": "7779",
            "CNPJ_Fundo": "38.542.889/0001-01",
            "Tipo_Fundo": "FII",
            "Denominacao_Social": "TREND ETF BLOOMBERG ALL COUNTRIES FUNDO DE ÍNDICE",
            "Situacao": "Em Funcionamento Normal",
            "Administrador": "XP INVESTIMENTOS CCTVM S.A.",
            "Gestor": "XP ALLOCATION ASSET MANAGEMENT LTDA.",
            "CPF_CNPJ_Gestor": "37.918.829/0001-79",
            "Patrimonio_Liquido": "356592737,05",
            "Data_Patrimonio_Liquido": "2026-08-25",
        }
        rec = self._capture([fundo_row])[0]
        assert rec["gestor_name"] == "XP ALLOCATION ASSET MANAGEMENT LTDA."
        assert rec["admin_name"] == "XP INVESTIMENTOS CCTVM S.A."
        assert rec["vl_patrim_liq"] == 356592737.05
