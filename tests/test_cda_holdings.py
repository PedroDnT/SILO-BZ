"""CDA holdings blocks 4 (equities) and 2 (fund quotas).

The fixtures below are cut from the real cda_fi_202606.zip, including the exact
shape of the collision that decided the block-4 key: the same fund holding the
same ticker under two different TP_APLIC values with different quantities. If a
future change drops TP_APLIC from the key, `test_tp_aplic_is_load_bearing` fails
rather than the collapse being discovered in production as a missing position.
"""

from datetime import date

import pytest

from src.parsers.field_maps import fi_cda_acoes as _acoes
from src.parsers.field_maps import fi_cda_cotas as _cotas
from src.pipeline.ingest_fi import ingest_fi_cda_acoes, ingest_fi_cda_cotas


class FakeConn:
    """Captures what would be upserted, so the test needs no database."""

    def __init__(self):
        self.calls = []


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_upsert(conn, table, rows, conflict_columns=None, **kw):
        seen["table"] = table
        seen["rows"] = rows
        seen["conflict"] = conflict_columns
        return len(rows)

    monkeypatch.setattr("src.pipeline.ingest_fi.upsert_rows", fake_upsert)
    return seen


# Two rows, same fund, same ticker, same TP_NEGOC — differing only in TP_APLIC.
# Verbatim shape from cda_fi_BLC_4_202606.csv.
ACOES_ROWS = [
    {
        "CNPJ_FUNDO_CLASSE": "00.102.322/0001-41", "DT_COMPTC": "2026-06-30",
        "TP_APLIC": "Ações", "TP_ATIVO": "Ação ordinária", "TP_NEGOC": "Para negociação",
        "CD_ATIVO": "ITUB3", "CD_ISIN": "BRITUBACNOR4", "DS_ATIVO": "ITAUUNIBANCO ON N1",
        "EMISSOR_LIGADO": "N", "QT_POS_FINAL": "186168.000000",
        "VL_MERC_POS_FINAL": "8241657.36", "VL_CUSTO_POS_FINAL": "",
        "QT_AQUIS_NEGOC": "0.000000", "VL_AQUIS_NEGOC": "0.00",
        "QT_VENDA_NEGOC": "0.000000", "VL_VENDA_NEGOC": "0.00",
    },
    {
        "CNPJ_FUNDO_CLASSE": "00.102.322/0001-41", "DT_COMPTC": "2026-06-30",
        "TP_APLIC": "Ações e outros TVM cedidos em empréstimo",
        "TP_ATIVO": "Ação ordinária", "TP_NEGOC": "Para negociação",
        "CD_ATIVO": "ITUB3", "CD_ISIN": "BRITUBACNOR4", "DS_ATIVO": "ITAUUNIBANCO ON N1",
        "EMISSOR_LIGADO": "N", "QT_POS_FINAL": "30914.000000",
        "VL_MERC_POS_FINAL": "22258.08", "VL_CUSTO_POS_FINAL": "",
        "QT_AQUIS_NEGOC": "", "VL_AQUIS_NEGOC": "",
        "QT_VENDA_NEGOC": "", "VL_VENDA_NEGOC": "",
    },
]

COTAS_ROWS = [
    {
        "CNPJ_FUNDO_CLASSE": "00.068.305/0001-35", "DT_COMPTC": "2026-06-30",
        "TP_APLIC": "Cotas de Fundos", "TP_ATIVO": "Fundo de Investimento e de Cotas",
        "EMISSOR_LIGADO": "S", "CNPJ_FUNDO_CLASSE_COTA": "01.165.780/0001-92",
        "NM_FUNDO_CLASSE_SUBCLASSE_COTA": "CAIXA MASTER PERSONALIZADO 50",
        "QT_POS_FINAL": "913625.012975", "VL_MERC_POS_FINAL": "40716791.57",
        "VL_CUSTO_POS_FINAL": "", "QT_AQUIS_NEGOC": "0.000000",
        "VL_AQUIS_NEGOC": "0.00", "QT_VENDA_NEGOC": "10602.001696",
        "VL_VENDA_NEGOC": "468401.00",
    },
]


def test_acoes_parses_the_ticker_and_position(captured):
    n = ingest_fi_cda_acoes(FakeConn(), ACOES_ROWS, 2026, 6)
    assert n == 2
    assert captured["table"] == "cvm_fi_cda_acoes"
    first = captured["rows"][0]
    assert first["cnpj"] == "00102322000141", "CNPJ punctuation must be stripped"
    assert first["cd_ativo"] == "ITUB3"
    assert first["qt_pos_final"] == pytest.approx(186168.0)
    assert first["vl_merc_pos_final"] == pytest.approx(8241657.36)


def test_period_is_normalised_to_first_of_month(captured):
    ingest_fi_cda_acoes(FakeConn(), ACOES_ROWS, 2026, 6)
    # DT_COMPTC is 2026-06-30; every monthly table in this warehouse keys on
    # first-of-month, and mixing the two grains silently splits a fund's history.
    assert {r["period"] for r in captured["rows"]} == {date(2026, 6, 1)}


def test_tp_aplic_is_load_bearing(captured):
    """The two fixture rows must survive as two rows, not collapse to one.

    They are the same fund, ticker and trading intent, differing only in
    TP_APLIC — and in quantity. Audited against the real file, dropping
    TP_APLIC from the key produced 3,972 collisions across 165,963 rows, each
    one a position value that an upsert would overwrite.
    """
    ingest_fi_cda_acoes(FakeConn(), ACOES_ROWS, 2026, 6)
    keys = {tuple(r[c] for c in _acoes.CONFLICT) for r in captured["rows"]}
    assert len(keys) == 2, "the conflict key must separate these two positions"
    assert "tp_aplic" in _acoes.CONFLICT


def test_acoes_conflict_key_matches_the_audit():
    assert _acoes.CONFLICT == ("cnpj", "period", "tp_aplic", "cd_ativo", "tp_negoc")


def test_a_row_without_a_ticker_is_dropped_not_invented(captured):
    """An equity holding with no CD_ATIVO cannot be joined to the tape.

    It is dropped and counted. Synthesising a ticker would make it joinable and
    wrong, which is the failure mode the ingest rules exist to prevent.
    """
    rows = ACOES_ROWS + [dict(ACOES_ROWS[0], CD_ATIVO="")]
    n = ingest_fi_cda_acoes(FakeConn(), rows, 2026, 6)
    assert n == 2
    assert all(r["cd_ativo"] for r in captured["rows"])


def test_cotas_parses_the_held_fund(captured):
    n = ingest_fi_cda_cotas(FakeConn(), COTAS_ROWS, 2026, 6)
    assert n == 1
    assert captured["table"] == "cvm_fi_cda_cotas"
    row = captured["rows"][0]
    assert row["cnpj"] == "00068305000135"
    assert row["cnpj_cota"] == "01165780000192", "the held fund is the point of this table"
    assert row["emissor_ligado"] == "S", "the published related-party flag must survive"


def test_cotas_conflict_key_matches_the_audit():
    assert _cotas.CONFLICT == ("cnpj", "period", "cnpj_cota")


def test_a_row_without_a_held_fund_is_dropped(captured):
    rows = COTAS_ROWS + [dict(COTAS_ROWS[0], CNPJ_FUNDO_CLASSE_COTA="")]
    assert ingest_fi_cda_cotas(FakeConn(), rows, 2026, 6) == 1


def test_unmapped_columns_are_preserved_in_raw(captured):
    """Provenance: a column we do not type must still reach the row, not vanish."""
    rows = [dict(ACOES_ROWS[0], DT_INI_VIGENCIA="2009-05-20")]
    ingest_fi_cda_acoes(FakeConn(), rows, 2026, 6)
    assert captured["rows"][0]["raw"].get("DT_INI_VIGENCIA") == "2009-05-20"


def test_both_blocks_come_from_the_archive_already_downloaded():
    """No new download: same URL as `cda`, a different member of the zip."""
    from src.fetchers.cvm_config import dataset_config

    urls = {
        dataset_config.get_dataset_config("fi", d)["url_pattern"]
        for d in ("cda", "cda_acoes", "cda_cotas")
    }
    assert len(urls) == 1, "these blocks must not trigger a second download"
    members = {
        dataset_config.get_dataset_config("fi", d)["csv_name_pattern"]
        for d in ("cda", "cda_acoes", "cda_cotas")
    }
    assert len(members) == 3


def test_blocks_are_wired_into_daily_and_backfill():
    """A dataset nobody calls is a dataset that never lands."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "pipeline" / "cvm_pipeline.py"
    body = src.read_text()
    for doc in ("cda_acoes", "cda_cotas"):
        assert f'self.ingest_fi_{doc}(year, month)' in body, f"{doc} missing from backfill"
        assert f'"cvm_fi_{doc}", "fi", "{doc}"' in body, f"{doc} missing from daily_update"
