"""FCA valores-mobiliários: the published CNPJ↔ticker map (cia_ticker).

Offline: rows are real lines from fca_cia_aberta_valor_mobiliario_2026.csv
(downloaded and verified 2026-08-27), parsed through the same apply_map path
the pipeline uses. No network, no database — upsert_rows is captured.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from src.parsers.field_maps import cia_fca_valor_mobiliario as fm
from src.parsers.mapping import apply_map
from src.pipeline import ingest_cia

# Verbatim structure from the live 2026 file (latin-1, ';'). BSLI3/BSLI4 is
# the important case: one CNPJ, two tickers, two share classes.
_FIXTURE = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;"
    "Valor_Mobiliario;Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;"
    "Codigo_Negociacao;Composicao_BDR_Unit;Mercado;Sigla_Entidade_Administradora;"
    "Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento;"
    "Data_Inicio_Listagem;Data_Fim_Listagem\n"
    "00.000.000/0001-91;2026-01-01;3;160576;BCO BRASIL S.A.;"
    "Ações Ordinárias;;;BBAS3;;Bolsa;B3;B3 S.A.;2006-05-31;;"
    "Novo Mercado;1977-07-20;\n"
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Ações Ordinárias;;;bsli3;;Bolsa;B3;B3 S.A.;2010-01-01;;"
    "Básico;1993-09-24;\n"
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Ações Preferenciais;;;BSLI4;;Bolsa;B3;B3 S.A.;2010-01-01;;"
    "Básico;1993-09-24;\n"
    # Unlisted security: no ticker. Kept in the table, skipped by the bridge.
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Debêntures;;;;;Balcão Organizado;B3;B3 S.A.;;;;;\n"
    # Unkeyable: no CNPJ. Must be dropped, never coerced.
    ";2026-01-01;1;0;GHOST;Ações Ordinárias;;;XXXX3;;Bolsa;B3;B3;;;;;\n"
)


def _rows():
    return list(csv.DictReader(io.StringIO(_FIXTURE), delimiter=";"))


class _CaptureConn:
    pass


def _run_ingest(monkeypatch, rows):
    captured = {}

    def fake_upsert(conn, table, records, conflict_columns):
        captured["table"] = table
        captured["records"] = records
        captured["conflict"] = conflict_columns
        return len(records)

    monkeypatch.setattr(ingest_cia, "upsert_rows", fake_upsert)
    n = ingest_cia.ingest_cia_ticker(_CaptureConn(), rows)
    return n, captured


def test_field_map_matches_the_live_header():
    # Every candidate column name must exist in the real header — this is the
    # drift guard that would have caught the FIAGRO rename incident.
    header = _rows()[0].keys()
    for col, (candidates, _t) in fm.FIELD_MAP.items():
        assert any(c in header for c in candidates), (
            f"{col}: none of {candidates} in the live FCA header"
        )


def test_rows_parse_with_published_identifiers(monkeypatch):
    n, cap = _run_ingest(monkeypatch, _rows())
    assert cap["table"] == "cia_ticker"
    assert cap["conflict"] == ",".join(fm.CONFLICT)
    # 4 keyable rows (ghost dropped): BBAS3, BSLI3, BSLI4, debenture-no-ticker
    assert n == 4
    by_ticker = {r["codneg"]: r for r in cap["records"]}
    assert by_ticker["BBAS3"]["cnpj_cia"] == "00000000000191"
    assert by_ticker["BBAS3"]["segmento"] == "Novo Mercado"
    assert str(by_ticker["BBAS3"]["data_refer"]) == "2026-01-01"
    # one CNPJ → two tickers, distinct share classes, from the same source rows
    assert by_ticker["BSLI3"]["cnpj_cia"] == by_ticker["BSLI4"]["cnpj_cia"]
    assert by_ticker["BSLI3"]["valor_mobiliario"].startswith("Ações Ordin")
    assert by_ticker["BSLI4"]["valor_mobiliario"].startswith("Ações Prefer")


def test_ticker_is_uppercased_to_match_the_b3_tape(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    assert all(
        r["codneg"] == r["codneg"].upper()
        for r in cap["records"]
        if r["codneg"] is not None
    )
    assert any(r["codneg"] == "BSLI3" for r in cap["records"])


def test_unlisted_security_is_kept_with_null_ticker(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    no_ticker = [r for r in cap["records"] if r["codneg"] is None]
    assert len(no_ticker) == 1
    assert no_ticker[0]["valor_mobiliario"].startswith("Deb")


def test_unkeyable_row_is_dropped_never_coerced(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    assert all(r["cnpj_cia"] for r in cap["records"])
    assert not any(r.get("codneg") == "XXXX3" for r in cap["records"])


def test_residual_lands_in_raw(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    bbas = next(r for r in cap["records"] if r["codneg"] == "BBAS3")
    assert bbas["raw"].get("Nome_Empresarial") == "BCO BRASIL S.A."


def test_dataset_is_configured_and_wired():
    from src.fetchers.cvm_config import dataset_config

    ds = dataset_config.get_dataset_config("cia_aberta", "fca_valor_mobiliario")
    assert ds["csv_name_pattern"] == "fca_cia_aberta_valor_mobiliario_{year}.csv"
    assert "/DOC/FCA/DADOS/" in ds["url_pattern"]

    # Wired into both entry points — an unwired dataset is never fetched.
    src = Path("src/pipeline/cvm_pipeline.py").read_text(encoding="utf-8")
    assert src.count("self.ingest_cia_fca(year)") >= 2, (
        "ingest_cia_fca must be wired into BOTH daily_update and backfill"
    )
    assert '"cia_ticker",' in src


def test_migration_25_bridge_is_published_mapping_only():
    sql = Path("src/store/migrations/25_cia_ticker.sql").read_text(encoding="utf-8")
    assert "UNIQUE NULLS NOT DISTINCT" in sql
    assert "CREATE OR REPLACE VIEW vw_company_ticker" in sql
    # The bridge must never fall back to name matching or ticker-shape guesses.
    assert "ILIKE" not in sql
    assert "denom" not in sql.lower()
    assert "DISTINCT ON (t.cnpj_cia, t.codneg)" in sql
    assert "t.data_refer DESC, t.versao DESC" in sql
