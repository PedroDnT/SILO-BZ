"""
FETCH → PARSE → VALIDATE tests for all CVM entity types.

HTTP is mocked at CVMFetcher._download. Supabase is stubbed.
Fixtures use real field names discovered via scripts/explore_cvm_output.py.

Field-mapping notes:
  FIDC/mensal:        targets tab_IV CSV; TAB_IV_A_VL_PL → vl_patrim_liq.
  FII/mensal_geral:   profile file only, no NAV — vl_patrim_liq is None.
  FII/mensal_complemento: contains Patrimonio_Liquido → vl_patrim_liq populated.
  SECURIT/cra_mensal: Valor_Atualizado_Emissao → vl_emissao; Ativo → vl_total;
                      Data_Referencia → dt_emissao (period reference date).
"""

import io
import zipfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.fetchers.cvm_fetcher import CVMFetcher
from src.pipeline.cvm_pipeline import (
    CVMIngestor,
    _normalize_cnpj,
    _find_field,
    _find_cnpj_field,
    _find_inadimpl,
)
from src.parsers.validation import DataValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv_bytes(rows: list[dict], encoding: str = "latin-1") -> bytes:
    if not rows:
        return b""
    cols = list(rows[0].keys())
    lines = [";".join(cols)]
    for row in rows:
        lines.append(";".join("" if row[c] is None else str(row[c]) for c in cols))
    return "\n".join(lines).encode(encoding)


def _make_zip_bytes(csv_name: str, rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, _make_csv_bytes(rows))  # bytes stored as-is, not re-encoded as UTF-8
    buf.seek(0)
    return buf.getvalue()


def _make_ingestor_with_capture():
    """Return (ingestor, captured_rows) with Supabase fully stubbed."""
    captured: list = []

    def fake_upsert(client, table, rows, conflict_columns=None):
        captured.extend(rows)
        return len(rows)

    with patch("src.pipeline.cvm_pipeline.get_supabase_client", return_value=MagicMock()):
        with patch("src.pipeline.cvm_pipeline.upsert_rows", side_effect=fake_upsert):
            ingestor = CVMIngestor()
    return ingestor, captured, fake_upsert


# W1 patch targets: after the refactor, upsert_rows is called from per-entity
# ingest modules (not from cvm_pipeline directly).  We need to patch in each
# module's namespace so the mock is active when the ingest function runs.
_UPSERT_PATCH_TARGETS = [
    "src.pipeline.ingest_fi.upsert_rows",
    "src.pipeline.ingest_fidc.upsert_rows",
    "src.pipeline.ingest_fii.upsert_rows",
    "src.pipeline.ingest_misc.upsert_rows",
    "src.pipeline.ingest_securit.upsert_rows",
    "src.pipeline.cvm_pipeline.upsert_rows",  # ingest_log calls
]
_PG_CLIENT_PATCH = "src.pipeline.cvm_pipeline.get_pg_client"


from contextlib import contextmanager

@contextmanager
def _stub_pipeline(captured: list):
    """Patch all upsert_rows and get_pg_client in one go."""
    def fake_upsert(client, table, rows, conflict_columns=None):
        if table != "cvm_ingest_log":
            captured.extend(rows)
        return len(rows)

    patches = [patch(t, side_effect=fake_upsert) for t in _UPSERT_PATCH_TARGETS]
    pg_patch = patch(_PG_CLIENT_PATCH, return_value=MagicMock())
    pg_patch.start()
    for p in patches:
        p.start()
    try:
        yield fake_upsert
    finally:
        for p in patches:
            p.stop()
        pg_patch.stop()


# ---------------------------------------------------------------------------
# Fixtures — real field names from CVM CSVs (exploration: 2025-05)
# ---------------------------------------------------------------------------

FI_DIARIO_ROWS = [
    {
        "TP_FUNDO_CLASSE": "FI",
        "CNPJ_FUNDO_CLASSE": "12.345.678/0001-90",
        "ID_SUBCLASSE": None,
        "DT_COMPTC": "2025-03-05",
        "VL_TOTAL": "1156886.57",
        "VL_QUOTA": "37.854676500000",
        "VL_PATRIM_LIQ": "1164101.50",
        "CAPTC_DIA": "0.00",
        "RESG_DIA": "0.00",
        "NR_COTST": "1",
    },
    {
        "TP_FUNDO_CLASSE": "FI",
        "CNPJ_FUNDO_CLASSE": "98.765.432/0001-10",
        "ID_SUBCLASSE": None,
        "DT_COMPTC": "2025-03-06",
        "VL_TOTAL": "2500000.00",
        "VL_QUOTA": "15.000000",
        "VL_PATRIM_LIQ": "2490000.00",
        "CAPTC_DIA": "100000.00",
        "RESG_DIA": "0.00",
        "NR_COTST": "42",
    },
]

FI_CDA_ROWS = [
    {
        "TP_FUNDO_CLASSE": "CLASSES - FIF",
        "CNPJ_FUNDO_CLASSE": "12.345.678/0001-90",
        "DENOM_SOCIAL": "FUNDO EXEMPLO FI",
        "DT_COMPTC": "2025-03-31",
        "TP_APLIC": "Operações Compromissadas",
        "TP_ATIVO": "Título público federal",
        "EMISSOR_LIGADO": "N",
        "TP_NEGOC": "Para negociação",
        "QT_VENDA_NEGOC": None,
        "VL_VENDA_NEGOC": None,
        "QT_AQUIS_NEGOC": None,
        "VL_AQUIS_NEGOC": None,
        "QT_POS_FINAL": "76.000000",
        "VL_MERC_POS_FINAL": "61529.46",
        "VL_CUSTO_POS_FINAL": None,
        "DT_CONFID_APLIC": None,
        "TP_TITPUB": "LETRAS DO TESOURO NACIONAL",
        "CD_ISIN": "BRSTNCLTN8G4",
        "CD_SELIC": "100000",
        "DT_EMISSAO": "2024-07-05",
        "DT_VENC": "2026-10-01",
    },
]

FIDC_MENSAL_ROWS = [
    {
        "TP_FUNDO_CLASSE": "Classe",
        "CNPJ_FUNDO_CLASSE": "12.345.678/0001-90",
        "DENOM_SOCIAL": "FUNDO EXEMPLO FIDC",
        "DT_COMPTC": "2025-03-31",
        "TAB_IV_A_VL_PL": "229108.78",
        "TAB_IV_B_VL_PL_MEDIO": "225000.00",
    },
]

FIP_QUADRIMESTRAL_ROWS = [
    {
        "TP_FUNDO_CLASSE": "CLASSES - FIP",
        "CNPJ_FUNDO_CLASSE": "12.345.678/0001-90",
        "DENOM_SOCIAL": "FUNDO EXEMPLO FIP",
        "DT_COMPTC": "2024-12-31",
        "VL_PATRIM_LIQ": "51024.920000000000",
        "QT_COTA": None,
        "VL_PATRIM_COTA": None,
        "NR_COTST": None,
        "ENTID_INVEST": "S",
        "PUBLICO_ALVO": "Investidores qualificados",
    },
]

# FII uses PascalCase field names; no Patrimonio_Liquido in mensal_geral
FII_MENSAL_GERAL_ROWS = [
    {
        "Tipo_Fundo_Classe": "Fundo",
        "CNPJ_Fundo_Classe": "12.345.678/0001-90",
        "Data_Referencia": "2024-01-01",
        "Versao": "1",
        "Data_Entrega": "2024-02-15",
        "Nome_Fundo_Classe": "FUNDO EXEMPLO FII",
        "Data_Funcionamento": "1994-11-24",
        "Publico_Alvo": "INVESTIDORES EM GERAL",
        "Codigo_ISIN": "BRFVPQCTF015",
        "Quantidade_Cotas_Emitidas": "2800149",
        "Fundo_Exclusivo": "N",
        "Cotistas_Vinculo_Familiar": "N",
        "Mandato": "Renda",
        "Segmento_Atuacao": "Shoppings",
        "Tipo_Gestao": "Passiva",
        "Prazo_Duracao": "Indeterminado",
        "Data_Prazo_Duracao": None,
    },
]

# FII complemento — contains Patrimonio_Liquido (30-col summary file)
FII_MENSAL_COMPLEMENTO_ROWS = [
    {
        "CNPJ_Fundo_Classe": "12.345.678/0001-90",
        "Data_Referencia": "2024-01-01",
        "Versao": "1",
        "Patrimonio_Liquido": "1500000.00",
        "Valor_Ativo": "1520000.00",
        "Total_Numero_Cotistas": "150",
        "Valor_Patrimonial_Cotas": "535.71",
        "Rendimento_Distribuido": "0.00",
    },
]

# SECURIT uses CNPJ_Emissora and camelCase/PascalCase names
SECURIT_CRA_ROWS = [
    {
        "CNPJ_Emissora": "12.345.678/0001-90",
        "Codigo_Identificacao_Certificado": "BRCBSCCRA047",
        "Data_Referencia": "2024-01-01",
        "Versao": "1",
        "Ativo": "604600612.97",
        "Direitos_Creditorios": "604555695.63",
        "Creditos_A_Vencer_Sem_Parcelas_Atraso": "604555695.63",
        "Creditos_A_Vencer_Com_Parcelas_Atraso": "0.00",
        "Creditos_Vencidos": "0.00",
        "Reducao_Valor_Recuperacao": "0.00",
        "Caixa_Equivalentes": "44917.34",
        "Caixa_Titulos_Publicos_Federais": "0.00",
        "Caixa_Cotas_Fundos": "44914.34",
        "Caixa_Operacoes_Compromissadas": "0.00",
        "Caixa_Outros": "3.00",
        "Passivo": "604600612.97",
        "Valor_Atualizado_Emissao": "604555695.63",
        "Reducao_Valor_Emissao": "0.00",
        "Outros_Passivos": "44917.34",
    },
]


# ---------------------------------------------------------------------------
# Helper-function unit tests (offline, no HTTP)
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    def test_normalize_cnpj_strips_punctuation(self):
        assert _normalize_cnpj("12.345.678/0001-90") == "12345678000190"

    def test_normalize_cnpj_already_digits(self):
        assert _normalize_cnpj("12345678000190") == "12345678000190"

    def test_normalize_cnpj_empty(self):
        assert _normalize_cnpj("") == ""

    def test_find_field_case_insensitive(self):
        row = {"DT_COMPTC": "2025-03-05", "VL_QUOTA": "37.85"}
        assert _find_field(row, "dt_comptc") == "2025-03-05"
        assert _find_field(row, "DT_COMPTC") == "2025-03-05"

    def test_find_field_first_candidate_wins(self):
        row = {"VL_TOTAL": "1000", "VL_CARTEIRA_TOTAL": "2000"}
        assert _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL") == "1000"

    def test_find_field_fallback(self):
        row = {"VL_CARTEIRA_TOTAL": "2000"}
        assert _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL") == "2000"

    def test_find_field_missing_returns_none(self):
        assert _find_field({"A": "1"}, "B") is None

    def test_find_cnpj_fi_diario(self):
        # FI inf_diario uses CNPJ_FUNDO_CLASSE; prefer_suffix="classe"
        row = FI_DIARIO_ROWS[0]
        result = _find_cnpj_field(row, prefer_suffix="classe")
        assert result == "12.345.678/0001-90"

    def test_find_cnpj_securit_fallback(self):
        # SECURIT real data uses CNPJ_Emissora, not CNPJ_SECURIT
        row = SECURIT_CRA_ROWS[0]
        result = _find_cnpj_field(row, prefer_suffix="securit")
        # prefer_suffix="securit" won't match CNPJ_Emissora, falls back to first CNPJ field
        assert result == "12.345.678/0001-90"

    def test_find_inadimpl_absent_in_fi(self):
        assert _find_inadimpl(FI_DIARIO_ROWS[0]) is None

    def test_find_inadimpl_absent_in_fidc_tab_fields(self):
        # FIDC tab_IV has NAV fields only; no inadimpl/delinq
        assert _find_inadimpl(FIDC_MENSAL_ROWS[0]) is None


# ---------------------------------------------------------------------------
# FETCH tests (mock HTTP → check column shapes)
# ---------------------------------------------------------------------------

class TestFIFetch:
    @pytest.mark.asyncio
    async def test_fi_diario_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("inf_diario_fi_202503.csv", FI_DIARIO_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fi", "inf_diario", year=2025, month=3)
        assert len(rows) == 2
        expected_cols = {"TP_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE", "DT_COMPTC",
                         "VL_TOTAL", "VL_QUOTA", "VL_PATRIM_LIQ", "CAPTC_DIA", "RESG_DIA", "NR_COTST"}
        assert expected_cols.issubset(set(rows[0].keys()))

    @pytest.mark.asyncio
    async def test_fi_cda_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("cda_fi_BLC_1_202503.csv", FI_CDA_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fi", "cda", year=2025, month=3)
        assert len(rows) == 1
        assert "TP_APLIC" in rows[0]
        assert "TP_ATIVO" in rows[0]
        assert "VL_MERC_POS_FINAL" in rows[0]


class TestFIDCFetch:
    @pytest.mark.asyncio
    async def test_fidc_mensal_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("inf_mensal_fidc_tab_IV_202503.csv", FIDC_MENSAL_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fidc", "mensal", year=2025, month=3)
        assert len(rows) == 1
        assert "CNPJ_FUNDO_CLASSE" in rows[0]
        assert "DT_COMPTC" in rows[0]
        assert "TAB_IV_A_VL_PL" in rows[0]


class TestFIPFetch:
    @pytest.mark.asyncio
    async def test_fip_quadrimestral_fetch_returns_expected_columns(self):
        # FIP is a plain CSV (not ZIP)
        mock_bytes = _make_csv_bytes(FIP_QUADRIMESTRAL_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fip", "inf_quadrimestral", year=2024)
        assert len(rows) == 1
        assert "CNPJ_FUNDO_CLASSE" in rows[0]
        assert "VL_PATRIM_LIQ" in rows[0]


class TestFIIFetch:
    @pytest.mark.asyncio
    async def test_fii_mensal_geral_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("inf_mensal_fii_geral_2024.csv", FII_MENSAL_GERAL_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fii", "mensal_geral", year=2024)
        assert len(rows) == 1
        assert "CNPJ_Fundo_Classe" in rows[0]
        assert "Data_Referencia" in rows[0]
        assert "Patrimonio_Liquido" not in rows[0]

    @pytest.mark.asyncio
    async def test_fii_mensal_complemento_fetch_has_patrimonio_liquido(self):
        mock_bytes = _make_zip_bytes("inf_mensal_fii_complemento_2024.csv", FII_MENSAL_COMPLEMENTO_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("fii", "mensal_complemento", year=2024)
        assert len(rows) == 1
        assert "Patrimonio_Liquido" in rows[0]
        assert rows[0]["Patrimonio_Liquido"] == "1500000.00"


class TestSECURITFetch:
    @pytest.mark.asyncio
    async def test_securit_cra_fetch_returns_expected_columns(self):
        mock_bytes = _make_zip_bytes("inf_mensal_cra_2024.csv", SECURIT_CRA_ROWS)
        with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
            fetcher = CVMFetcher()
            rows = await fetcher.fetch("securit", "cra_mensal", year=2024)
        assert len(rows) == 1
        assert "CNPJ_Emissora" in rows[0]
        assert "Data_Referencia" in rows[0]
        assert "Valor_Atualizado_Emissao" in rows[0]
        # Real data does NOT have the pipeline's expected field names
        assert "DT_EMISSAO" not in rows[0]
        assert "VL_EMISSAO" not in rows[0]


# ---------------------------------------------------------------------------
# PARSE tests (pipeline normalization with real field names)
# ---------------------------------------------------------------------------

class TestCVMPipelineFieldMapping:
    """Test that the pipeline correctly maps real CVM field names to output records.

    W1 refactor: values are now coerced to typed Python objects by apply_map():
      - dates   -> datetime.date
      - numeric -> float
      - int     -> int
      - cnpj    -> str (14 digits, zero-padded)
      - text    -> str

    upsert_rows is patched in every ingest_* module's namespace via _stub_pipeline.
    """

    @pytest.mark.asyncio
    async def test_fi_diario_pipeline_extracts_all_fields(self):
        import datetime
        mock_bytes = _make_zip_bytes("inf_diario_fi_202503.csv", FI_DIARIO_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                count = await ingestor.ingest_fi_diario(2025, 3)

        assert count == 2
        assert len(captured) == 2
        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["tp_fundo"] == "FI"
        assert rec["dt_comptc"] == datetime.date(2025, 3, 5)
        assert rec["vl_total"] == pytest.approx(1156886.57, rel=1e-6)
        assert rec["vl_quota"] == pytest.approx(37.8546765, rel=1e-6)
        assert rec["vl_patrim_liq"] == pytest.approx(1164101.50, rel=1e-6)
        assert rec["captc_dia"] == pytest.approx(0.0, abs=1e-6)
        assert rec["resg_dia"] == pytest.approx(0.0, abs=1e-6)
        assert rec["nr_cotst"] == 1
        assert "raw" in rec

    @pytest.mark.asyncio
    async def test_fi_cda_pipeline_extracts_key_fields(self):
        import datetime
        mock_bytes = _make_zip_bytes("cda_fi_BLC_1_202503.csv", FI_CDA_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_fi_cda(2025, 3)

        assert len(captured) == 1
        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["period"] == datetime.date(2025, 3, 1)
        assert rec["tp_aplic"] == "Operações Compromissadas"
        assert rec["tp_ativo"] == "Título público federal"
        assert rec["vl_merc_pos_final"] == pytest.approx(61529.46, rel=1e-6)

    @pytest.mark.asyncio
    async def test_fidc_mensal_pipeline_extracts_patrim_liq(self):
        """FIDC tab_IV data: TAB_IV_A_VL_PL is mapped to vl_patrim_liq."""
        import datetime
        mock_bytes = _make_zip_bytes("inf_mensal_fidc_tab_IV_202503.csv", FIDC_MENSAL_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_fidc_mensal(2025, 3)

        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["period"] == datetime.date(2025, 3, 31)
        assert rec["vl_patrim_liq"] == pytest.approx(229108.78, rel=1e-6)
        assert rec["vl_total"] is None
        assert rec["vl_quota"] is None

    @pytest.mark.asyncio
    async def test_fip_quadrimestral_pipeline_extracts_vl_patrim_liq(self):
        mock_bytes = _make_csv_bytes(FIP_QUADRIMESTRAL_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_fip_periodic("inf_quadrimestral", 2024)

        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["doc_type"] == "inf_quadrimestral"
        assert rec["period_year"] == 2024
        assert rec["vl_patrim_liq"] == pytest.approx(51024.92, rel=1e-4)

    @pytest.mark.asyncio
    async def test_fii_mensal_geral_pipeline_cnpj_and_period(self):
        import datetime
        mock_bytes = _make_zip_bytes("inf_mensal_fii_geral_2024.csv", FII_MENSAL_GERAL_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_fii_mensal("mensal_geral", 2024)

        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["period"] == datetime.date(2024, 1, 1)
        assert rec["doc_subtype"] == "geral"
        # vl_patrim_liq is not in the geral FIELD_MAP so it is absent from the record
        assert "vl_patrim_liq" not in rec

    @pytest.mark.asyncio
    async def test_fii_mensal_complemento_pipeline_extracts_patrim_liq(self):
        import datetime
        mock_bytes = _make_zip_bytes("inf_mensal_fii_complemento_2024.csv", FII_MENSAL_COMPLEMENTO_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_fii_mensal("mensal_complemento", 2024)

        rec = captured[0]
        assert rec["cnpj"] == "12345678000190"
        assert rec["period"] == datetime.date(2024, 1, 1)
        assert rec["doc_subtype"] == "complemento"
        assert rec["vl_patrim_liq"] == pytest.approx(1500000.0, rel=1e-6)

    @pytest.mark.asyncio
    async def test_securit_cra_pipeline_extracts_real_field_names(self):
        """SECURIT: real CVM PascalCase names are now mapped correctly."""
        import datetime
        mock_bytes = _make_zip_bytes("inf_mensal_cra_2024.csv", SECURIT_CRA_ROWS)
        captured: list = []

        with _stub_pipeline(captured):
            with patch.object(CVMFetcher, "_download", new_callable=AsyncMock, return_value=mock_bytes):
                ingestor = CVMIngestor()
                await ingestor.ingest_securit_mensal("cra_mensal", 2024)

        rec = captured[0]
        assert rec["instrument_type"] == "cra_mensal"
        assert rec["period_year"] == 2024
        assert rec["dt_emissao"] == datetime.date(2024, 1, 1)
        assert rec["vl_emissao"] == pytest.approx(604555695.63, rel=1e-6)
        assert rec["vl_total"] == pytest.approx(604600612.97, rel=1e-6)
        assert rec["vl_unit"] is None
        assert rec["qt_titulos"] is None


# ---------------------------------------------------------------------------
# VALIDATE tests (DataValidator on real-shaped rows)
# ---------------------------------------------------------------------------

class TestValidatorOnCVMShapedData:
    def test_fi_diario_dataset_report_structure(self):
        validator = DataValidator()
        report = validator.validate_dataset(FI_DIARIO_ROWS)
        assert report["total_records"] == 2
        assert "quality_score" in report
        assert "parsing_success_rate" in report
        assert "field_stats" in report
        # All expected columns are tracked in field_stats
        for col in ("TP_FUNDO_CLASSE", "DT_COMPTC", "VL_TOTAL", "VL_PATRIM_LIQ"):
            assert col in report["field_stats"]

    def test_fi_cda_dataset_report_structure(self):
        validator = DataValidator()
        report = validator.validate_dataset(FI_CDA_ROWS)
        assert report["total_records"] == 1
        assert "TP_APLIC" in report["field_stats"]
        assert "VL_MERC_POS_FINAL" in report["field_stats"]

    def test_fidc_mensal_report_shows_tab_iv_fields(self):
        validator = DataValidator()
        report = validator.validate_dataset(FIDC_MENSAL_ROWS)
        assert "TAB_IV_A_VL_PL" in report["field_stats"]
        assert "TAB_IV_B_VL_PL_MEDIO" in report["field_stats"]
        # tab_IV does not have VL_TOTAL / VL_QUOTA
        assert "VL_TOTAL" not in report["field_stats"]
        assert "VL_QUOTA" not in report["field_stats"]

    def test_fip_report_has_vl_patrim_liq(self):
        validator = DataValidator()
        report = validator.validate_dataset(FIP_QUADRIMESTRAL_ROWS)
        assert "VL_PATRIM_LIQ" in report["field_stats"]
        # Null fields tracked
        fii_vl_patrim = report["field_stats"]["VL_PATRIM_LIQ"]
        assert fii_vl_patrim["total"] == 1

    def test_fii_mensal_geral_no_patrimonio_liquido_field(self):
        validator = DataValidator()
        report = validator.validate_dataset(FII_MENSAL_GERAL_ROWS)
        assert "Data_Referencia" in report["field_stats"]
        # Confirms the mismatch: no wealth field present
        assert "Patrimonio_Liquido" not in report["field_stats"]
        assert "VL_PATRIM_LIQ" not in report["field_stats"]

    def test_securit_report_tracks_cnpj_emissora(self):
        validator = DataValidator()
        report = validator.validate_dataset(SECURIT_CRA_ROWS)
        assert "CNPJ_Emissora" in report["field_stats"]
        assert "Valor_Atualizado_Emissao" in report["field_stats"]

    def test_validator_errors_and_warnings_are_lists(self):
        validator = DataValidator()
        report = validator.validate_dataset(FI_DIARIO_ROWS)
        assert isinstance(report["validation_errors"], list)
        assert isinstance(report["warnings"], list)

    def test_validate_record_returns_error_for_bad_cnpj(self):
        validator = DataValidator()
        bad_row = {**FI_DIARIO_ROWS[0], "CNPJ_FUNDO_CLASSE": "INVALID_CNPJ"}
        errors, _warnings = validator.validate_record(
            bad_row, field_types={"CNPJ_FUNDO_CLASSE": "cnpj"}
        )
        assert len(errors) > 0
        assert any("cnpj" in str(e).lower() or "CNPJ" in str(e) for e in errors)

    def test_validate_record_no_errors_without_cnpj_type_hint(self):
        """Without explicit field_types, validator auto-detects by name.
        Rows without CNPJ fields produce no errors."""
        validator = DataValidator()
        row = {"DT_COMPTC": "2025-03-05", "VL_TOTAL": "1000.00"}
        errors, _warnings = validator.validate_record(row)
        assert len(errors) == 0
