"""Share counts and the free float of listed companies (#1161).

Offline: the fixture rows are real lines from the CVM files (ITR 2025
composição do capital, FRE 2010 capital social and distribuição do capital,
downloaded 2026-11-16), parsed through the same apply_map path the pipeline
uses. No network, no database: upsert_rows is captured.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from src.parsers.field_maps import cia_composicao_capital as cc
from src.parsers.field_maps import cia_fre_capital_social as cap
from src.parsers.field_maps import cia_fre_distribuicao_capital as ff
from src.pipeline import ingest_cia

ROOT = Path(__file__).resolve().parents[1]

_COMPOSICAO = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;"
    "QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
    "00.000.000/0001-91;2025-03-31;1;BCO BRASIL S.A.;5730834040;0;5730834040;22370429;0;22370429\n"
    "00.000.000/0001-91;2025-06-30;1;BCO BRASIL S.A.;5730834040;0;5730834040;22370399;0;22370399\n"
    # Unkeyable: no CNPJ. Dropped, never coerced.
    ";2025-06-30;1;GHOST;1;0;1;0;0;0\n"
    # A negative count is not a count. Dropped.
    "00.000.000/0001-91;2025-09-30;1;BCO BRASIL S.A.;-5;0;-5;0;0;0\n"
)

_FRE_CAPITAL = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;ID_Capital_Social;"
    "Tipo_Capital;Data_Autorizacao_Aprovacao;Valor_Capital;Prazo_Integralizacao;"
    "Quantidade_Acoes_Ordinarias;Quantidade_Acoes_Preferenciais;Quantidade_Total_Acoes\n"
    "00.000.000/0001-91;2010-01-01;11;9670;BCO BRASIL S.A.;36654;Capital Emitido;2010-04-13;"
    "33077996200.75;Capital integralizado no total;2860729247;0;2860729247\n"
    "00.000.000/0001-91;2010-01-01;11;9670;BCO BRASIL S.A.;36655;Capital Subscrito;2010-04-13;"
    "33077996200.75;;2860729247;0;2860729247\n"
)

_FRE_FLOAT = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;Quantidade_Acionistas_PF;"
    "Quantidade_Acionistas_PJ;Quantidade_Acionistas_Investidores_Institucionais;"
    "Quantidade_Acoes_Ordinarias_Circulacao;Percentual_Acoes_Ordinarias_Circulacao;"
    "Quantidade_Acoes_Preferenciais_Circulacao;Percentual_Acoes_Preferenciais_Circulacao;"
    "Quantidade_Total_Acoes_Circulacao;Percentual_Total_Acoes_Circulacao;Data_Ultima_Assembleia\n"
    "00.000.000/0001-91;2025-12-31;22;157774;BCO BRASIL S.A.;1492490;15317;1196;2842496541;"
    "49.600000;0;0.000000;2842496541;49.600000;2025-04-30\n"
    "00.000.208/0001-00;2025-12-31;37;161387;BRB BANCO DE BRASILIA S.A.;4167;46;3;79340652;"
    "24.785000;85770503;51.650000;165111155;33.961000;2025-11-26\n"
)


def _rows(text):
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def _capture(monkeypatch):
    captured = {}

    def fake_upsert(conn, table, records, conflict_columns):
        captured.update(table=table, records=records, conflict=conflict_columns)
        return len(records)

    monkeypatch.setattr(ingest_cia, "upsert_rows", fake_upsert)
    return captured


@pytest.mark.parametrize("fm, text", [(cc, _COMPOSICAO), (cap, _FRE_CAPITAL), (ff, _FRE_FLOAT)])
def test_field_map_matches_the_live_header(fm, text):
    header = _rows(text)[0].keys()
    for col, (candidates, _t) in fm.FIELD_MAP.items():
        assert any(c in header for c in candidates), f"{col}: none of {candidates} in the header"


def test_share_counts_are_keyed_and_unkeyable_rows_dropped(monkeypatch):
    cap_ = _capture(monkeypatch)
    n = ingest_cia.ingest_cia_share_count(object(), _rows(_COMPOSICAO), "itr")
    assert n == 2 and cap_["table"] == "cia_share_count"
    assert cap_["conflict"] == ",".join(cc.CONFLICT)
    r = cap_["records"][0]
    assert r["cnpj_cia"] == "00000000000191" and r["doc_type"] == "itr"
    assert r["qt_total"] == 5730834040 and r["qt_total_tesouro"] == 22370429
    assert r["raw"]["DENOM_CIA"] == "BCO BRASIL S.A."


def test_share_counts_refuse_an_unknown_doc_type():
    with pytest.raises(ValueError):
        ingest_cia.ingest_cia_share_count(object(), _rows(_COMPOSICAO), "fre")


def test_fre_capital_keeps_every_capital_type(monkeypatch):
    cap_ = _capture(monkeypatch)
    n = ingest_cia.ingest_cia_fre_capital(object(), _rows(_FRE_CAPITAL))
    assert n == 2 and cap_["table"] == "cia_fre_capital"
    assert {r["tipo_capital"] for r in cap_["records"]} == {"Capital Emitido", "Capital Subscrito"}
    assert all(r["qt_total"] == 2860729247 and r["versao"] == 11 for r in cap_["records"])


def test_fre_free_float_keeps_counts_and_percent_as_filed(monkeypatch):
    cap_ = _capture(monkeypatch)
    n = ingest_cia.ingest_cia_fre_free_float(object(), _rows(_FRE_FLOAT))
    assert n == 2 and cap_["table"] == "cia_fre_free_float"
    brb = next(r for r in cap_["records"] if r["cnpj_cia"] == "00000208000100")
    assert brb["qt_pref_circ"] == 85770503 and brb["pct_pref_circ"] == pytest.approx(51.65)
    assert brb["pct_total_circ"] == pytest.approx(33.961) and brb["n_acionistas_inst"] == 3


def test_datasets_are_configured_conditional_and_wired():
    from src.fetchers.conditional import is_conditional_slice
    from src.fetchers.cvm_config import dataset_config

    for doc_type, member in [
        ("itr_composicao_capital", "itr_cia_aberta_composicao_capital_{year}.csv"),
        ("dfp_composicao_capital", "dfp_cia_aberta_composicao_capital_{year}.csv"),
        ("fre_capital_social", "fre_cia_aberta_capital_social_{year}.csv"),
        ("fre_distribuicao_capital", "fre_cia_aberta_distribuicao_capital_{year}.csv"),
    ]:
        ds = dataset_config.get_dataset_config("cia_aberta", doc_type)
        assert ds["csv_name_pattern"] == member
        assert is_conditional_slice("cia_aberta", doc_type)
    src = (ROOT / "src/pipeline/cvm_pipeline.py").read_text(encoding="utf-8")
    assert src.count("self._cia_share_count_tasks(") == 2, "wire into BOTH daily_update and backfill"


def test_backfill_plans_composicao_from_2020_and_fre_from_2010():
    from src.pipeline.cvm_pipeline import CVMIngestor

    ingestor = CVMIngestor(service=object(), cia_fetcher=object(), client=object())
    tasks = ingestor._cia_share_count_tasks([2010, 2019, 2020])
    try:
        names = {t.description for t in tasks}
        assert "cia_aberta/fre_capital_social 2010" in names
        assert "cia_aberta/fre_distribuicao_capital 2019" in names
        assert "cia_aberta/itr_composicao_capital 2020" in names
        assert "cia_aberta/itr_composicao_capital 2019" not in names
        assert len(tasks) == 2 + 2 + 4
    finally:
        for t in tasks:
            t.operation.close()


def test_schema_and_migration_carry_the_same_named_constraints():
    schema = (ROOT / "src/store/schema.sql").read_text(encoding="utf-8")
    mig = (ROOT / "src/store/migrations/86_cia_share_counts.sql").read_text(encoding="utf-8")
    for name in ("uq_cia_share_count", "uq_cia_fre_capital", "uq_cia_fre_free_float"):
        assert f"CONSTRAINT {name} UNIQUE NULLS NOT DISTINCT" in schema
        assert f"CONSTRAINT {name} UNIQUE NULLS NOT DISTINCT" in mig
