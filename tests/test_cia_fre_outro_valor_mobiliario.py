"""FRE "outros valores mobiliários": debt issues of listed companies (#1164).

Offline: rows follow the live fre_cia_aberta_outro_valor_mobiliario_2025.csv
(header checked 2026-11-16), parsed by the fetcher's own CSV reader and the
same apply_map path the pipeline uses. No network, no database: upsert_rows is
captured.
"""

from __future__ import annotations

from pathlib import Path

from src.fetchers.cvm_fetcher import CVMFetcher
from src.parsers.field_maps import cia_fre_outro_valor_mobiliario as fm
from src.pipeline import ingest_cia

_HEADER = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;"
    "Valor_Mobiliario;Identificacao_Valor_Mobiliario;Data_Emissao;Data_Vencimento;"
    "Quantidade;Valor;Quantidade_Pessoa_Fisica;Quantidade_Pessoa_Juridica;"
    "Quantidade_Investidor_Institucional;Saldo_Devedor;Restricao_Circulacao;"
    "Descricao_Restricao_Circulacao;Conversibilidade;"
    "Condicao_Conversibilidade_Efeito_Capital_Social;Resgatavel;"
    "Hipotese_Resgate_Formula_Calculo;Caracteristicas_Valores_Mobiliarios_Divida;"
    "Condicao_Alteracao_Direitos;Outras_Caracteristicas_Relevantes\n"
)

_AXIA = (
    "00.001.180/0001-26;2025-12-31;21;156737;AXIA ENERGIA S.A.;Debêntures;"
    "1ª Emissão de Debêntures Simples;2019-11-15;2029-11-15;1250000;1250000000.00;"
    ";;;1066524000.00;Sim;Somente investidores qualificados;;;Sim;"
    "Resgate facultativo;"
    # Quoted multi-line free text, as CVM ships it.
    '"Vencimento: 15/11/2029.\nRemuneração: IPCA + 4,50% a.a.";'
    "Assembleia;Ver escritura\n"
)

_FIXTURE = (
    _HEADER
    + _AXIA
    # The same row again: an exact repeat collapses into one record.
    + _AXIA
    # Same document and issue name, different text: a real second row. A
    # descriptive key would merge it; row_hash keeps both.
    + "00.001.180/0001-26;2025-12-31;21;156737;AXIA ENERGIA S.A.;Debêntures;"
    "1ª Emissão de Debêntures Simples;2019-11-15;2029-11-15;1250000;1250000000.00;"
    ";;;1066524000.00;Sim;Somente investidores qualificados;;;Sim;"
    "Resgate facultativo;Remuneração: 100% DI + 1,20% a.a.;Assembleia;Ver escritura\n"
    # Empty flags stay NULL, never False.
    + "02.421.421/0001-11;2025-12-31;4;160001;TIM S.A.;Nota Comercial;"
    "1ª Emissão de Notas Comerciais;2024-03-01;2027-03-01;500;500000000.00;"
    ";;;500000000.00;;;;;;;;;\n"
    # No version: cannot be keyed, so it is dropped.
    + "02.421.421/0001-11;2025-12-31;;160002;TIM S.A.;Debêntures;"
    "2ª Emissão;2021-06-15;2028-06-15;1600000;1600000000.00;;;;;;;;;;;;;\n"
)


def _rows():
    fetcher = CVMFetcher.__new__(CVMFetcher)
    fetcher.separator = ";"
    return fetcher._parse_csv(_FIXTURE)


def _run_ingest(monkeypatch, rows):
    captured = {}

    def fake_upsert(conn, table, records, conflict_columns):
        captured["table"] = table
        captured["records"] = records
        captured["conflict"] = conflict_columns
        return len(records)

    monkeypatch.setattr(ingest_cia, "upsert_rows", fake_upsert)
    n = ingest_cia.ingest_cia_fre_outro_valor_mobiliario(object(), rows)
    return n, captured


def test_field_map_matches_the_live_header():
    header = _rows()[0].keys()
    for col, (candidates, _t) in fm.FIELD_MAP.items():
        assert any(c in header for c in candidates), col


def test_multiline_text_is_one_field():
    rows = _rows()
    assert len(rows) == 5
    assert rows[0]["Caracteristicas_Valores_Mobiliarios_Divida"] == (
        "Vencimento: 15/11/2029.\nRemuneração: IPCA + 4,50% a.a."
    )


def test_repeats_collapse_and_distinct_rows_survive(monkeypatch):
    n, cap = _run_ingest(monkeypatch, _rows())
    assert cap["table"] == "cvm_fre_outro_valor_mobiliario"
    assert cap["conflict"] == "cnpj_cia,data_refer,versao,id_documento,row_hash"
    # 5 rows: 1 exact repeat collapsed, 1 without a version dropped.
    assert n == 3
    keys = [tuple(r[c] for c in fm.CONFLICT) for r in cap["records"]]
    assert len(set(keys)) == len(keys)
    axia = [r for r in cap["records"] if r["cnpj_cia"] == "00001180000126"]
    assert len(axia) == 2


def test_values_as_filed(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    axia = next(r for r in cap["records"]
                if r["cnpj_cia"] == "00001180000126"
                and r["caracteristicas_divida"].startswith("Vencimento"))
    assert axia["versao"] == 21
    assert str(axia["data_vencimento"]) == "2029-11-15"
    assert axia["valor"] == 1250000000.0
    assert axia["saldo_devedor"] == 1066524000.0
    assert axia["restricao_circulacao"] is True
    assert axia["conversibilidade"] is None
    # Unmapped columns are kept in raw; the rate text is stored, not parsed.
    assert axia["raw"]["Outras_Caracteristicas_Relevantes"] == "Ver escritura"
    assert "indexer" not in axia and "rate" not in axia
    tim = next(r for r in cap["records"] if r["cnpj_cia"] == "02421421000111")
    assert tim["restricao_circulacao"] is None
    assert tim["resgatavel"] is None


def test_dataset_is_configured_and_wired():
    from src.fetchers.conditional import is_conditional_slice
    from src.fetchers.cvm_config import dataset_config

    ds = dataset_config.get_dataset_config("cia_aberta", "fre_outro_valor_mobiliario")
    assert ds["csv_name_pattern"] == "fre_cia_aberta_outro_valor_mobiliario_{year}.csv"
    assert "/DOC/FRE/DADOS/" in ds["url_pattern"]
    assert is_conditional_slice("cia_aberta", "fre_outro_valor_mobiliario")
    src = Path("src/pipeline/cvm_pipeline.py").read_text(encoding="utf-8")
    assert src.count("self.ingest_cia_fre_ovm(year)") == 2, (
        "ingest_cia_fre_ovm must be wired into BOTH daily_update and backfill"
    )


def test_migration_and_schema_agree():
    mig = Path("src/store/migrations/86_cvm_fre_outro_valor_mobiliario.sql").read_text(
        encoding="utf-8")
    schema = Path("src/store/schema.sql").read_text(encoding="utf-8")
    for sql in (mig, schema):
        assert "CREATE TABLE IF NOT EXISTS cvm_fre_outro_valor_mobiliario" in sql
        assert "UNIQUE (cnpj_cia, data_refer, versao, id_documento, row_hash)" in sql
        assert "REVOKE ALL ON cvm_fre_outro_valor_mobiliario FROM PUBLIC" in sql
    assert "GRANT" not in mig
