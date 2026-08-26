"""Regressions for the silent data-loss bugs found in the daily ingest logs.

Each of these failed in production while the workflow reported success, because
the pipeline logs a per-slice failure and moves on. The fixtures below carry the
*real* CVM headers (fetched from dados.cvm.gov.br) so a future source rename
fails here instead of quietly emptying a table.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os

import pytest

from src.parsers.mapping import apply_map
from src.parsers.field_maps import fidc_aging as _aging
from src.parsers.field_maps import fidc_mensal as _mensal
from src.parsers.field_maps import securit_fluxo as _fluxo
from src.pipeline.cvm_pipeline import _describe


def _rows(header: str, *lines: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO("\n".join((header, *lines))), delimiter=";"))


# --------------------------------------------------------------------------
# 1. securit_fluxo — CVM renamed every key column; the map matched none of
#    them, so assert_map_matches raised and cvm_securit_fluxo stayed empty.
# --------------------------------------------------------------------------

# Real header of inf_mensal_cra_fluxo_caixa_2026.csv.
CRA_FLUXO_HEADER = (
    "CNPJ_Emissora;Codigo_Identificacao_Certificado;Data_Referencia;Versao;"
    "Recebimentos_Direitos_Creditorios;Pagamentos_Despesas;Pagamentos_Classe_Senior;"
    "Pagamentos_Classe_Senior_Amortizacao_Principal;Pagamentos_Classe_Senior_Juros;"
    "Pagamentos_Classe_Subordinada_Mezanino;"
    "Pagamentos_Classe_Subordinada_Mezanino_Amortizacao_Principal;"
    "Pagamentos_Classe_Subordinada_Mezanino_Juros;"
    "Pagamentos_Classe_Subordinada_Junior;"
    "Pagamentos_Classe_Subordinada_Junior_Amortizacao_Principal;"
    "Pagamentos_Classe_Subordinada_Junior_Juros;Recebimentos_Alienacao_Caixa;"
    "Aquisicao_Caixa;Aquisicao_Novos_Direitos_Creditorios;Outros_Recebimentos;"
    "Outros_Pagamentos;Variacao_Liquida_Caixa"
)
CRA_FLUXO_ROW = (
    "02773542000122;BRAPCSCRA0M6;2026-01-01;1;16914866,02;-2375,65;16814848,75;"
    "16000000,00;814848,75;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00;0,00;97641,62"
)

# OTS/CRI use CNPJ_Securitizadora and Recebimentos_Creditos instead.
OTS_FLUXO_HEADER = CRA_FLUXO_HEADER.replace(
    "CNPJ_Emissora", "CNPJ_Securitizadora"
).replace("Recebimentos_Direitos_Creditorios", "Recebimentos_Creditos")


@pytest.mark.parametrize("header", [CRA_FLUXO_HEADER, OTS_FLUXO_HEADER])
def test_securit_fluxo_maps_the_live_cvm_header(header):
    """Every required key must resolve, or the whole dataset lands zero rows."""
    row = _rows(header, CRA_FLUXO_ROW)[0]
    typed, residual = apply_map(row, _fluxo.FIELD_MAP)

    assert typed["cnpj_securit"] == "02773542000122"
    assert typed["codigo_identificacao"] == "BRAPCSCRA0M6"
    assert typed["data_referencia"].isoformat() == "2026-01-01"
    # The principal legs ship as ..._Amortizacao_Principal.
    assert typed["pagamentos_senior_principal"] == 16000000.00
    assert typed["pagamentos_senior_juros"] == 814848.75
    assert typed["recebimentos_direitos_creditorios"] == 16914866.02
    assert typed["variacao_liquida_caixa"] == 97641.62
    # Unmodelled columns survive in the raw residual rather than vanishing.
    assert "Versao" in residual


def test_securit_fluxo_required_key_is_present_in_the_map():
    """ingest_securit_fluxo asserts on codigo_identificacao — keep a candidate."""
    candidates, _ = _fluxo.FIELD_MAP["codigo_identificacao"]
    assert "Codigo_Identificacao_Certificado" in candidates


# --------------------------------------------------------------------------
# 2. fidc_mensal — tab_IV has no delinquency column at all, so vl_inadimpl was
#    NULL for every 2025+ month and every downstream screen read blank.
# --------------------------------------------------------------------------

# Real header of inf_mensal_fidc_tab_IV_202607.csv — six columns, no inadimpl.
TAB_IV_HEADER = (
    "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;"
    "TAB_IV_A_VL_PL;TAB_IV_B_VL_PL_MEDIO"
)
TAB_IV_ROW = "Classe;12345678000199;FUNDO TESTE FIDC;2026-07-31;1000000,00;990000,00"

TAB_VI_HEADER = (
    "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC;"
    "TAB_VI_A_VL_DIRCRED_PRAZO;TAB_VI_B_VL_DIRCRED_INAD"
)
TAB_VI_ROW = "Classe;12345678000199;FUNDO TESTE FIDC;2026-07-31;800000,00;125000,00"


def test_tab_iv_alone_cannot_supply_delinquency():
    """Documents the root cause: the column simply is not in this file."""
    row = _rows(TAB_IV_HEADER, TAB_IV_ROW)[0]
    typed, _ = apply_map(row, _mensal.FIELD_MAP)
    assert typed["vl_patrim_liq"] == 1000000.00
    assert typed["vl_inadimpl"] is None


def test_fidc_mensal_merges_delinquency_from_tab_vi(monkeypatch):
    """tab_VI's total is joined on (cnpj, period) — same ZIP, same grain."""
    captured = {}

    def fake_upsert(conn, table, records, conflict_columns):
        captured["records"] = records
        return len(records)

    monkeypatch.setattr("src.pipeline.ingest_fidc.upsert_rows", fake_upsert)
    from src.pipeline.ingest_fidc import ingest_fidc_mensal

    n = ingest_fidc_mensal(
        conn=None,
        raw_rows=_rows(TAB_IV_HEADER, TAB_IV_ROW),
        rows_vi=_rows(TAB_VI_HEADER, TAB_VI_ROW),
    )

    assert n == 1
    rec = captured["records"][0]
    assert rec["cnpj"] == "12345678000199"
    assert rec["vl_patrim_liq"] == 1000000.00
    assert rec["vl_inadimpl"] == 125000.00


def test_fidc_mensal_leaves_delinquency_null_without_tab_vi(monkeypatch):
    """A missing tab_VI must stay NULL — never a zero, never a carried value."""
    captured = {}
    monkeypatch.setattr(
        "src.pipeline.ingest_fidc.upsert_rows",
        lambda conn, table, records, conflict_columns: captured.setdefault(
            "records", records
        ) and len(records),
    )
    from src.pipeline.ingest_fidc import ingest_fidc_mensal

    ingest_fidc_mensal(None, _rows(TAB_IV_HEADER, TAB_IV_ROW), rows_vi=None)
    assert captured["records"][0]["vl_inadimpl"] is None


def test_fidc_mensal_does_not_join_across_periods(monkeypatch):
    """A tab_VI row from another month must not leak into this month's row."""
    captured = {}
    monkeypatch.setattr(
        "src.pipeline.ingest_fidc.upsert_rows",
        lambda conn, table, records, conflict_columns: captured.setdefault(
            "records", records
        ) and len(records),
    )
    from src.pipeline.ingest_fidc import ingest_fidc_mensal

    other_month = TAB_VI_ROW.replace("2026-07-31", "2026-06-30")
    ingest_fidc_mensal(
        None,
        _rows(TAB_IV_HEADER, TAB_IV_ROW),
        rows_vi=_rows(TAB_VI_HEADER, other_month),
    )
    assert captured["records"][0]["vl_inadimpl"] is None


def test_aging_map_still_reads_the_tab_vi_total():
    """The merge reuses fidc_aging's map — keep its total wired to tab_VI."""
    row = _rows(TAB_VI_HEADER, TAB_VI_ROW)[0]
    typed, _ = apply_map(row, _aging.FIELD_MAP)
    assert typed["vl_total_inad"] == 125000.00


# --------------------------------------------------------------------------
# 3. Cache writes raced: four datasets share each monthly ZIP, wrote the same
#    path concurrently, and readers saw half-written bytes ("not a zip file").
# --------------------------------------------------------------------------


def test_cache_write_is_atomic_and_leaves_no_partial_file(tmp_path, monkeypatch):
    from src.fetchers.cvm_fetcher import CVMFetcher

    monkeypatch.setattr("src.fetchers.cvm_fetcher.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("src.fetchers.cvm_fetcher.config.TEMP_DIR", str(tmp_path))
    fetcher = CVMFetcher()
    cache_path = str(tmp_path / "x.cache")
    meta_path = str(tmp_path / "x.meta")

    payload = b"PK\x03\x04" + b"z" * 4096
    asyncio.run(fetcher._save_cache(cache_path, meta_path, payload, "http://x"))

    assert open(cache_path, "rb").read() == payload
    assert json.load(open(meta_path))["size"] == len(payload)
    # The temp files used for the atomic rename must not linger.
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_concurrent_downloads_of_one_url_fetch_once(tmp_path, monkeypatch):
    """Single-flight: the datasets sharing a ZIP must not stampede it."""
    from src.fetchers.cvm_fetcher import CVMFetcher

    monkeypatch.setattr("src.fetchers.cvm_fetcher.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("src.fetchers.cvm_fetcher.config.TEMP_DIR", str(tmp_path))
    fetcher = CVMFetcher()
    calls = []

    async def fake_uncached(url, cache_path, meta_path):
        calls.append(url)
        await asyncio.sleep(0)  # let the other waiters run
        await fetcher._save_cache(cache_path, meta_path, b"PK\x03\x04data", url)
        return b"PK\x03\x04data"

    monkeypatch.setattr(fetcher, "_download_uncached", fake_uncached)

    async def main():
        url = "http://cvm/inf_mensal_fidc_202607.zip"
        return await asyncio.gather(*(fetcher._download(url) for _ in range(4)))

    results = asyncio.run(main())

    assert results == [b"PK\x03\x04data"] * 4
    assert len(calls) == 1, f"expected one fetch for the shared ZIP, got {len(calls)}"


# --------------------------------------------------------------------------
# 4. Arg-less exceptions logged as an empty string.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, expected",
    [
        (ValueError(), "ValueError"),
        (ValueError(""), "ValueError"),
        (ValueError("Data not found"), "ValueError: Data not found"),
        (__import__("zipfile").BadZipFile("File is not a zip file"),
         "BadZipFile: File is not a zip file"),
    ],
)
def test_describe_never_returns_an_empty_reason(exc, expected):
    assert _describe(exc) == expected
    assert _describe(exc).strip(), "an audit row must always name a cause"


# --------------------------------------------------------------------------
# 5. CVM retired FII/CAD/ entirely; the daily run kept fetching it and logging
#    an error every morning. registro_fundo already carries every FII.
# --------------------------------------------------------------------------


def test_fii_cadastral_endpoint_is_no_longer_configured():
    from src.fetchers.cvm_config import dataset_config

    assert "cad" not in dataset_config.get_available_doc_types("fii"), (
        "FII/CAD/DADOS/cad_fii.csv is a dead CVM path (the directory 404s); "
        "FII registry rows come from the CVM-175 registro_fundo dataset"
    )


def test_cvm175_registry_routes_fii_rows_to_the_fii_entity_type():
    from src.pipeline.ingest_misc import _entity_from_tipo

    # Tipo_Fundo values as they appear in the real registro_fundo.csv.
    assert _entity_from_tipo("FII") == "fii"
    assert _entity_from_tipo("FIIM") == "fii"
    assert _entity_from_tipo("FIDC") == "fidc"
    assert _entity_from_tipo("FIAGRO") == "fiagro"
