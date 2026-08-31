"""CDA block 6 — the fund to corporate-credit edge, and why its key ends in a hash.

Block 6 is debenture holdings: which company's debt a fund holds, at what
maturity, indexed to what, at what spread. CPF_CNPJ_EMISSOR is the issuer's own
CNPJ, so it joins to the cia_* listed-company universe the same way block 4's
CD_ATIVO joins to the quote tape.

The fixtures below are cut verbatim from cda_fi_BLC_6_2015.csv and
cda_fi_BLC_6_202606.csv, including the Telefônica pair that decided row_hash's
place in the key.
"""

from datetime import date

import pytest

from src.parsers.field_maps import fi_cda_debentures as _deb
from src.pipeline.ingest_fi import ingest_fi_cda_debentures


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


def _hist(**over):
    """A 2005-2022 HIST row: CNPJ_FUNDO / TP_FUNDO, the pre-CVM-175 names."""
    base = {
        "TP_FUNDO": "FAPI",
        "CNPJ_FUNDO": "10.546.592/0001-03",
        "DENOM_SOCIAL": "BB FAPI FUNDO DE APOSENTADORIA PROGRAMADA INDIVIDUAL",
        "DT_COMPTC": "2015-01-31",
        "TP_APLIC": "Debêntures",
        "TP_ATIVO": "Debênture simples",
        "EMISSOR_LIGADO": "N",
        "TP_NEGOC": "Para negociação",
        "QT_POS_FINAL": "20.000000",
        "VL_MERC_POS_FINAL": "205349.27",
        "PF_PJ_EMISSOR": "PJ",
        "CPF_CNPJ_EMISSOR": "02.558.157/0001-62",
        "EMISSOR": "TELEFÔNICA BRAS",
        "DT_VENC": "2018-04-25",
        "TITULO_POSFX": "S",
        "CD_INDEXADOR_POSFX": "DI1",
        "DS_INDEXADOR_POSFX": "DI de um dia",
        "PR_INDEXADOR_POSFX": "100.000000",
        "PR_CUPOM_POSFX": "0.678357",
        "PR_TAXA_PREFX": "",
        "TITULO_CETIP": "S",
        "TITULO_GARANTIA": "N",
        "CNPJ_INSTITUICAO_FINANC_COOBR": "",
    }
    base.update(over)
    return base


def _monthly(**over):
    """A 2023+ monthly row: CNPJ_FUNDO_CLASSE / TP_FUNDO_CLASSE."""
    base = {
        "TP_FUNDO_CLASSE": "CLASSES - FIF",
        "CNPJ_FUNDO_CLASSE": "00.807.777/0001-62",
        "DENOM_SOCIAL": "DAYCOVAL CLASSE DE INVESTIMENTO RENDA FIXA CRÉDITO PRIVADO",
        "DT_COMPTC": "2026-06-30",
        "TP_APLIC": "Debêntures",
        "TP_ATIVO": "Debênture simples",
        "EMISSOR_LIGADO": "N",
        "TP_NEGOC": "Para negociação",
        "QT_POS_FINAL": "5198.000000",
        "VL_MERC_POS_FINAL": "456308.15",
        "PF_PJ_EMISSOR": "PJ",
        "CPF_CNPJ_EMISSOR": "01.599.101/0001-93",
        "EMISSOR": "SEQUOIA LOGÍSTICA E TRANSPORTES S.A.",
        "DT_VENC": "2027-12-31",
        "TITULO_POSFX": "S",
        "CD_INDEXADOR_POSFX": "DI1",
        "DS_INDEXADOR_POSFX": "DI de um dia",
        "PR_INDEXADOR_POSFX": "100.000000",
        "PR_CUPOM_POSFX": "0.000000",
        "PR_TAXA_PREFX": "",
        "TITULO_CETIP": "S",
        "TITULO_GARANTIA": "N",
        "CNPJ_INSTITUICAO_FINANC_COOBR": "",
    }
    base.update(over)
    return base


# The pair that decided the key. Same fund, same month, same issuer, same
# maturity — two Telefônica series separated only by their coupon. Verbatim from
# cda_fi_BLC_6_2015.csv, where 16,910 collision groups differ in exactly this
# column.
TELEFONICA = [
    _hist(PR_CUPOM_POSFX="0.678357"),
    _hist(PR_CUPOM_POSFX="0.814597"),
]


def test_two_series_of_one_issuer_are_two_positions(captured):
    """The bug this key exists to prevent, in one assertion.

    A key that stopped at tp_negoc would put both of these on one row and keep
    whichever was written last. That is 15.8% of every historical file.
    """
    n = ingest_fi_cda_debentures(object(), TELEFONICA, 2015, None)
    assert n == 2
    keys = {tuple(r[c] for c in _deb.CONFLICT) for r in captured["rows"]}
    assert len(keys) == 2, "the two coupons must not collapse onto one row"
    assert sorted(float(r["pr_cupom_posfx"]) for r in captured["rows"]) == [
        pytest.approx(0.678357), pytest.approx(0.814597),
    ]


def test_the_natural_key_still_leads_the_hash():
    """row_hash is a tiebreaker, not the key.

    A key that led with a digest could not serve (fund, period) or
    (issuer, period) range scans — the two lookups this table exists for.
    """
    assert _deb.CONFLICT[-1] == "row_hash"
    assert _deb.CONFLICT[:8] == (
        "cnpj", "period", "tp_fundo", "tp_aplic", "tp_ativo",
        "cpf_cnpj_emissor", "dt_venc", "tp_negoc",
    )


def test_reingesting_an_unchanged_file_is_a_noop(captured):
    """Deterministic digest: the same source rows produce the same keys."""
    ingest_fi_cda_debentures(object(), TELEFONICA, 2015, None)
    first = {tuple(r[c] for c in _deb.CONFLICT) for r in captured["rows"]}
    ingest_fi_cda_debentures(object(), TELEFONICA, 2015, None)
    assert {tuple(r[c] for c in _deb.CONFLICT) for r in captured["rows"]} == first


def test_a_yearly_archive_keeps_each_row_own_month(captured):
    """month=None means every row dates itself from DT_COMPTC.

    Stamping one month on a whole-year HIST file is the collapse that cost
    cvm_fi_cda eleven of twelve months for every year from 2005 to 2022.
    """
    year = [_hist(DT_COMPTC=f"2015-{m:02d}-28") for m in range(1, 13)]
    n = ingest_fi_cda_debentures(object(), year, 2015, None)
    assert n == 12
    assert {r["period"] for r in captured["rows"]} == {
        date(2015, m, 1) for m in range(1, 13)
    }


def test_a_monthly_archive_takes_the_month_it_was_given(captured):
    """The 2023+ files are one competency month each, so the caller decides."""
    ingest_fi_cda_debentures(object(), [_monthly()], 2026, 6)
    assert captured["rows"][0]["period"] == date(2026, 6, 1)


def test_both_column_eras_parse(captured):
    """CVM-175 renamed CNPJ_FUNDO to CNPJ_FUNDO_CLASSE mid-history.

    Without the fallback every pre-2023 row would have no CNPJ and be dropped —
    which is exactly what happened to block 2 before its map was fixed.
    """
    ingest_fi_cda_debentures(object(), [_hist()], 2015, None)
    assert captured["rows"][0]["cnpj"] == "10546592000103"
    assert captured["rows"][0]["tp_fundo"] == "FAPI"

    ingest_fi_cda_debentures(object(), [_monthly()], 2026, 6)
    assert captured["rows"][0]["cnpj"] == "00807777000162"
    assert captured["rows"][0]["tp_fundo"] == "CLASSES - FIF"


def test_a_row_with_no_issuer_is_dropped_not_stored(captured):
    """cpf_cnpj_emissor is what makes the row joinable.

    Storing one without it would put a position in the table that no query can
    attribute to a company — the holding equivalent of an equity row with no
    ticker.
    """
    n = ingest_fi_cda_debentures(
        object(), [_hist(), _hist(CPF_CNPJ_EMISSOR="")], 2015, None
    )
    assert n == 1
    assert all(r["cpf_cnpj_emissor"] for r in captured["rows"])


def test_a_cpf_issuer_is_kept_not_rejected(captured):
    """PF_PJ_EMISSOR says this column may hold an 11-digit CPF.

    Running it through the CNPJ validator would drop a real filing, so the
    column is stored as published text and PF_PJ_EMISSOR records which it is.
    """
    row = _hist(PF_PJ_EMISSOR="PF", CPF_CNPJ_EMISSOR="123.456.789-09")
    n = ingest_fi_cda_debentures(object(), [row], 2015, None)
    assert n == 1
    assert captured["rows"][0]["pf_pj_emissor"] == "PF"
    assert captured["rows"][0]["cpf_cnpj_emissor"]


def test_a_row_with_no_date_is_dropped_not_dated(captured):
    """Without DT_COMPTC there is no honest period to give a HIST row."""
    n = ingest_fi_cda_debentures(
        object(), TELEFONICA + [_hist(DT_COMPTC="")], 2015, None
    )
    assert n == 2


def test_the_rate_structure_is_typed_not_left_in_raw(captured):
    """The spread is the point: 'holds Telefônica' without it says little."""
    ingest_fi_cda_debentures(object(), [_hist()], 2015, None)
    row = captured["rows"][0]
    assert row["cd_indexador_posfx"] == "DI1"
    assert float(row["pr_indexador_posfx"]) == pytest.approx(100.0)
    assert float(row["pr_cupom_posfx"]) == pytest.approx(0.678357)
    assert row["dt_venc"] == date(2018, 4, 25)


def test_it_writes_to_its_own_table(captured):
    ingest_fi_cda_debentures(object(), [_hist()], 2015, None)
    assert captured["table"] == "cvm_fi_cda_debentures"
    assert captured["conflict"] == ",".join(_deb.CONFLICT)
