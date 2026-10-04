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


class TestRegistryFees:
    """cad_fi.csv publishes the disclosed fee; the CVM-175 registro files do not.

    The registro upsert must leave the fee columns out of its records entirely:
    upsert_rows builds its INSERT column list and its ON CONFLICT SET list from
    the first record's keys (src/store/pg_client.py), so an absent key is a
    column the upsert never writes, and the fee the cad upsert stored survives.
    """

    CAD_ROW = {
        "TP_FUNDO": "FI",
        "CNPJ_FUNDO": "11.222.333/0001-44",
        "DENOM_SOCIAL": "ALPHA FIM",
        "SIT": "EM FUNCIONAMENTO NORMAL",
        "TAXA_ADM": "1.5",
        "TAXA_PERFM": "20",
        "INF_TAXA_ADM": "",
        "INF_TAXA_PERFM": "20% DO QUE EXCEDER O CDI",
        "DT_INI_EXERC": "2025-01-01",
        "DT_FIM_EXERC": "2025-12-31",
        "CLASSE": "Multimercado",
    }
    # registro_classe.csv header names, trimmed: it publishes no fee column.
    REGISTRO_ROW = {
        "ID_Registro_Classe": "36019",
        "CNPJ_Classe": "11.222.333/0001-44",
        "Denominacao_Social": "ALPHA FIF CLASSE",
        "Tipo_Classe": "Classes de Cotas de Fundos FIF",
        "Situacao": "Em Funcionamento Normal",
        "Classificacao": "Multimercado",
        "Publico_Alvo": "Geral",
    }
    FEE_COLS = ("taxa_adm", "taxa_perfm", "inf_taxa_adm", "inf_taxa_perfm",
                "dt_ini_exerc", "dt_fim_exerc")

    @staticmethod
    def _capture(fn, target, rows):
        captured = {}

        def _fake_upsert(conn, table, recs, **kw):
            captured["recs"] = recs
            return len(recs)

        with patch(target, side_effect=_fake_upsert):
            fn(object(), rows)
        return captured["recs"]

    def test_cad_maps_the_six_fee_columns_as_filed(self):
        from src.pipeline.ingest_fi import ingest_fund_registry_fi

        (rec,) = self._capture(
            ingest_fund_registry_fi, "src.pipeline.ingest_fi.upsert_rows", [self.CAD_ROW]
        )
        assert rec["taxa_adm"] == 1.5
        assert rec["taxa_perfm"] == 20.0
        assert rec["inf_taxa_adm"] is None          # empty in the source stays NULL
        assert rec["inf_taxa_perfm"] == "20% DO QUE EXCEDER O CDI"
        assert str(rec["dt_ini_exerc"]) == "2025-01-01"
        assert str(rec["dt_fim_exerc"]) == "2025-12-31"
        # Mapped headers leave raw; unmapped ones stay there.
        assert "TAXA_ADM" not in rec["raw"]
        assert rec["raw"]["CLASSE"] == "Multimercado"

    def test_registro_upsert_after_cad_does_not_touch_the_fee(self):
        from src.pipeline.ingest_fi import ingest_fund_registry_fi

        cad = self._capture(
            ingest_fund_registry_fi, "src.pipeline.ingest_fi.upsert_rows", [self.CAD_ROW]
        )
        registro = self._capture(
            ingest_fund_registry_cvm175, "src.pipeline.ingest_misc.upsert_rows",
            [self.REGISTRO_ROW],
        )
        # Both land on the same row: (cnpj, entity_type) agree.
        assert (cad[0]["cnpj"], cad[0]["entity_type"]) == (
            registro[0]["cnpj"], registro[0]["entity_type"])
        assert cad[0]["taxa_adm"] == 1.5
        for rec in registro:
            for col in self.FEE_COLS:
                assert col not in rec, col

    def test_upsert_sql_names_only_the_record_keys(self):
        """The guarantee above rests on upsert_rows writing only the keys it gets."""
        from src.store import pg_client

        seen = []

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Client:
            def cursor(self):
                return _Cur()

        def _fake_execute_values(cur, sql, values, *a, **kw):
            seen.append(sql)

        with patch("psycopg2.extras.execute_values", side_effect=_fake_execute_values):
            pg_client.upsert_rows(
                _Client(), "cvm_fund_registry",
                [{"cnpj": "11222333000144", "entity_type": "fi", "fund_name": "X"}],
                conflict_columns="cnpj,entity_type",
            )
        assert seen, "upsert_rows issued no statement"
        assert "fund_name=EXCLUDED.fund_name" in seen[0]
        assert "taxa_adm" not in seen[0]
