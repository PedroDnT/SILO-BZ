"""FIDC tabs I, II, VIII and X — concentration and credit quality, as filed.

Fixtures are cut verbatim from inf_mensal_fidc_202607.zip (Caterpillar FIDC,
BBIF Master, one fund whose first cedente slot is an 11-digit CPF) and from the
2024-12 member of the HIST archive, which is the other era of the same header.
"""

from datetime import date

import pytest

from src.parsers.field_maps import fidc_cedente as _cedente
from src.parsers.field_maps import fidc_sacado as _sacado
from src.parsers.field_maps import fidc_scr as _scr
from src.parsers.field_maps import fidc_setor as _setor
from src.parsers.mapping import FieldMapMismatch
from src.pipeline.ingest_fidc import (
    ingest_fidc_cedente,
    ingest_fidc_mensal,
    ingest_fidc_sacado,
    ingest_fidc_scr,
    ingest_fidc_setor,
)


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_upsert(conn, table, rows, conflict_columns=None, **kw):
        seen["table"] = table
        seen["rows"] = rows
        seen["conflict"] = conflict_columns
        return len(rows)

    monkeypatch.setattr("src.pipeline.ingest_fidc.upsert_rows", fake_upsert)
    return seen


_KEY = {
    "TP_FUNDO_CLASSE": "Classe",
    "CNPJ_FUNDO_CLASSE": "05.754.060/0001-13",
    "DENOM_SOCIAL": "CATERPILLAR FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS DO SEGMENTO INDUSTRIAL II - RESP LIMITADA",
    "DT_COMPTC": "2026-07-31",
}


def _tab_i(**over):
    """Caterpillar's 2026-07 tab_I cedente slots: two block-A cedentes, no block B."""
    row = dict(_KEY)
    for blk in ("A", "B"):
        for i in range(1, 10):
            row[f"TAB_I2{blk}12_CPF_CNPJ_CEDENTE_{i}"] = ""
            row[f"TAB_I2{blk}12_PR_CEDENTE_{i}"] = ""
    row.update({
        "TAB_I2A12_CPF_CNPJ_CEDENTE_1": "61064911000177",
        "TAB_I2A12_PR_CEDENTE_1": "72.41",
        "TAB_I2A12_CPF_CNPJ_CEDENTE_2": "61064911001734",
        "TAB_I2A12_PR_CEDENTE_2": "10.47",
    })
    row.update(over)
    return row


def _tab_viii(seq, valor, **over):
    row = {
        "TP_FUNDO_CLASSE": "Classe",
        "CNPJ_FUNDO_CLASSE": "11.003.181/0001-26",
        "DENOM_SOCIAL": "BBIF MASTER FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS LP",
        "DT_COMPTC": "2026-07-31",
        "SEQUENCIAL": seq,
        "VALOR": valor,
    }
    row.update(over)
    return row


_TAB_II_ZERO_COLS = [
    "TAB_II_A_VL_INDUST", "TAB_II_B_VL_IMOBIL", "TAB_II_C_VL_COMERC", "TAB_II_C1_VL_COMERC",
    "TAB_II_C2_VL_VAREJO", "TAB_II_C3_VL_ARREND", "TAB_II_D2_VL_SERV_PUBLICO",
    "TAB_II_D3_VL_SERV_EDUC", "TAB_II_D4_VL_ENTRET", "TAB_II_E_VL_AGRONEG", "TAB_II_F_VL_FINANC",
    "TAB_II_F1_VL_CRED_PESSOA", "TAB_II_F2_VL_CRED_PESSOA_CONSIG", "TAB_II_F3_VL_CRED_CORP",
    "TAB_II_F4_VL_MIDMARKET", "TAB_II_F5_VL_VEICULO", "TAB_II_F6_VL_IMOBIL_EMPRESA",
    "TAB_II_F7_VL_IMOBIL_RESID", "TAB_II_F8_VL_OUTRO", "TAB_II_G_VL_CREDITO", "TAB_II_H_VL_FACTOR",
    "TAB_II_H1_VL_PESSOA", "TAB_II_H2_VL_CORP", "TAB_II_I_VL_SETOR_PUBLICO", "TAB_II_I1_VL_PRECAT",
    "TAB_II_I2_VL_TRIBUT", "TAB_II_I3_VL_ROYALTIES", "TAB_II_I4_VL_OUTRO", "TAB_II_J_VL_JUDICIAL",
    "TAB_II_K_VL_MARCA",
]


def _tab_ii(**over):
    """Caterpillar 2026-07: the whole portfolio is services (D / D1)."""
    row = dict(_KEY)
    row["TAB_II_VL_CARTEIRA"] = "1403730252.03"
    row["TAB_II_D_VL_SERV"] = "1403730252.03"
    row["TAB_II_D1_VL_SERV"] = "1403730252.03"
    for c in _TAB_II_ZERO_COLS:
        row[c] = "0.00"
    row.update(over)
    return row


def _tab_x(**over):
    row = dict(_KEY)
    for grade in ("AA", "A", "B", "C", "D", "E", "F", "G", "H"):
        row[f"TAB_X_SCR_RISCO_DEVEDOR_{grade}"] = "0.00"
        row[f"TAB_X_SCR_RISCO_OPER_{grade}"] = "0.00"
    row["TAB_X_SCR_RISCO_DEVEDOR_AA"] = "1403730252.03"
    row["TAB_X_SCR_RISCO_OPER_AA"] = "1403730252.03"
    row["TAB_X_DEBITO_TRIBUT"] = "0.00"
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# tab_I — named cedentes, unpivoted
# ---------------------------------------------------------------------------

def test_cedente_unpivots_only_filled_slots(captured):
    n = ingest_fidc_cedente(None, [_tab_i()])

    assert captured["table"] == "cvm_fidc_cedente"
    assert captured["conflict"] == "cnpj,period,bloco,seq"
    assert n == 2
    rows = sorted(captured["rows"], key=lambda r: r["seq"])
    assert rows[0] == {
        "cnpj": "05754060000113", "period": date(2026, 7, 31),
        "bloco": "A", "seq": 1,
        "cpf_cnpj_cedente": "61064911000177", "pr_cedente": 72.41,
    }
    assert rows[1]["cpf_cnpj_cedente"] == "61064911001734"
    assert rows[1]["pr_cedente"] == 10.47
    # the fourteen empty block-A slots and all of block B produce nothing
    assert {r["bloco"] for r in rows} == {"A"}


def test_cedente_cpf_is_kept_as_filed_not_padded_to_cnpj(captured):
    # 26.199.650/0001-00 files an 11-digit CPF in its first block-A slot
    # (2026-07). `cnpj` coercion would zero-pad it into a fake CNPJ.
    row = _tab_i(
        CNPJ_FUNDO_CLASSE="26.199.650/0001-00",
        TAB_I2A12_CPF_CNPJ_CEDENTE_1="10443515603",
        TAB_I2A12_PR_CEDENTE_1="18.00",
        TAB_I2A12_CPF_CNPJ_CEDENTE_2="",
        TAB_I2A12_PR_CEDENTE_2="",
    )
    ingest_fidc_cedente(None, [row])
    (r,) = captured["rows"]
    assert r["cpf_cnpj_cedente"] == "10443515603"
    assert len(r["cpf_cnpj_cedente"]) == 11


@pytest.mark.parametrize("filed, kept", [
    # 2026-07 block-B slots that lost leading zeros upstream; each pads to a
    # CNPJ whose check digits verify.
    ("6084614000185", "06084614000185"),
    ("5099585000162", "05099585000162"),
    ("938858000100",  "00938858000100"),
    ("3990431000130", "03990431000130"),
])
def test_cedente_dropped_leading_zero_is_recovered_only_when_checksum_verifies(captured, filed, kept):
    ingest_fidc_cedente(None, [_tab_i(
        TAB_I2A12_CPF_CNPJ_CEDENTE_1=filed, TAB_I2A12_CPF_CNPJ_CEDENTE_2="", TAB_I2A12_PR_CEDENTE_2="",
    )])
    (r,) = captured["rows"]
    assert r["cpf_cnpj_cedente"] == kept


@pytest.mark.parametrize("placeholder", [
    "00000000000000",  # 06.018.364/0001-85, every slot, 2022-12 and 2024-12
    "99999999999999",  # 05.754.060/0001-13 in the 2018 form
    "0",
    "12345678000100",  # 14 digits, check digits do not verify
    "123",             # pads to neither a CNPJ nor a CPF that verifies
])
def test_cedente_placeholder_or_invalid_identifier_is_dropped_not_coerced(captured, placeholder):
    n = ingest_fidc_cedente(None, [_tab_i(
        TAB_I2A12_CPF_CNPJ_CEDENTE_1=placeholder, TAB_I2A12_PR_CEDENTE_1="50.00",
        TAB_I2A12_CPF_CNPJ_CEDENTE_2="", TAB_I2A12_PR_CEDENTE_2="",
    )])
    assert n == 0
    assert "rows" not in captured


def test_cedente_identifier_rule_directly():
    from src.pipeline.ingest_fidc import cedente_identifier

    assert cedente_identifier("61.064.911/0001-77") == "61064911000177"
    assert cedente_identifier("10443515603") == "10443515603"      # a CPF, as filed
    assert cedente_identifier("6084614000185") == "06084614000185"  # a CNPJ, recovered
    assert cedente_identifier("") is None
    assert cedente_identifier(None) is None
    assert cedente_identifier("99999999999999") is None
    assert cedente_identifier("104435156030000") is None            # 15 digits: nothing it could be


def test_cedente_block_b_and_formatted_identifier(captured):
    row = _tab_i(
        TAB_I2B12_CPF_CNPJ_CEDENTE_1="07.652.226/0001-16",
        TAB_I2B12_PR_CEDENTE_1="32.21",
    )
    ingest_fidc_cedente(None, [row])
    b = [r for r in captured["rows"] if r["bloco"] == "B"]
    assert b == [{
        "cnpj": "05754060000113", "period": date(2026, 7, 31),
        "bloco": "B", "seq": 1,
        "cpf_cnpj_cedente": "07652226000116", "pr_cedente": 32.21,
    }]


def test_cedente_share_may_be_blank_beside_an_identifier(captured):
    row = _tab_i(TAB_I2A12_PR_CEDENTE_2="")
    ingest_fidc_cedente(None, [row])
    by_seq = {r["seq"]: r for r in captured["rows"]}
    assert by_seq[2]["pr_cedente"] is None


def test_cedente_drops_rows_missing_the_fund_key(captured):
    n = ingest_fidc_cedente(None, [_tab_i(DT_COMPTC="")])
    assert n == 0
    assert "rows" not in captured


def test_cedente_header_drift_raises():
    row = _tab_i()
    for k in list(row):
        if "CEDENTE" in k:
            row[k.replace("CEDENTE", "ORIGINADOR")] = row.pop(k)
    with pytest.raises(FieldMapMismatch):
        ingest_fidc_cedente(None, [row])


def test_cedente_map_covers_all_36_slot_columns():
    slots = [c for c in _cedente.FIELD_MAP if c.startswith(("cedente_", "pr_"))]
    assert len(slots) == 36
    cands = {_cedente.FIELD_MAP[c][0][0] for c in slots}
    assert "TAB_I2A12_CPF_CNPJ_CEDENTE_9" in cands
    assert "TAB_I2B12_PR_CEDENTE_9" in cands


# ---------------------------------------------------------------------------
# tab_VIII — the 25 largest sacados, as filed
# ---------------------------------------------------------------------------

def test_sacado_one_row_per_rank_as_filed(captured):
    rows = [
        _tab_viii("1", "67861219.95"),
        _tab_viii("2", "58906547.12"),
        _tab_viii("3", "51448277.06"),
        _tab_viii("4", "32013501.50"),
    ]
    n = ingest_fidc_sacado(None, rows)

    assert n == 4
    assert captured["table"] == "cvm_fidc_sacado"
    assert captured["conflict"] == "cnpj,period,seq"
    assert captured["rows"][0] == {
        "cnpj": "11003181000126", "period": date(2026, 7, 31),
        "seq": 1, "valor": 67861219.95,
    }
    assert [r["seq"] for r in captured["rows"]] == [1, 2, 3, 4]


def test_sacado_is_never_reranked(captured):
    # 65 of 3,043 funds in 2026-07 file a non-descending series; it is CVM's
    # rank, stored as filed.
    rows = [_tab_viii("1", "10.00"), _tab_viii("2", "20.00")]
    ingest_fidc_sacado(None, rows)
    assert [(r["seq"], r["valor"]) for r in captured["rows"]] == [(1, 10.0), (2, 20.0)]


def test_sacado_zero_value_rank_is_kept(captured):
    # 09.260.031/0001-56 files a single rank-1 row of 0.00 (2026-08).
    ingest_fidc_sacado(None, [_tab_viii("1", "0.00", CNPJ_FUNDO_CLASSE="09.260.031/0001-56")])
    assert captured["rows"] == [{
        "cnpj": "09260031000156", "period": date(2026, 7, 31), "seq": 1, "valor": 0.0,
    }]


def test_sacado_row_without_rank_is_dropped_not_guessed(captured):
    n = ingest_fidc_sacado(None, [_tab_viii("", "1.00"), _tab_viii("2", "1.00")])
    assert n == 1
    assert captured["rows"][0]["seq"] == 2


def test_sacado_hist_era_row_has_the_same_shape(captured):
    # 2024-12 member of the HIST archive, verbatim.
    row = {
        "TP_FUNDO_CLASSE": "Classe",
        "CNPJ_FUNDO_CLASSE": "05.754.060/0001-13",
        "DENOM_SOCIAL": _KEY["DENOM_SOCIAL"],
        "DT_COMPTC": "2024-12-31",
        "SEQUENCIAL": "1",
        "VALOR": "1338943091.17",
    }
    ingest_fidc_sacado(None, [row])
    assert captured["rows"] == [{
        "cnpj": "05754060000113", "period": date(2024, 12, 31), "seq": 1, "valor": 1338943091.17,
    }]


# ---------------------------------------------------------------------------
# tab_II — portfolio by sector
# ---------------------------------------------------------------------------

def test_setor_wide_row_with_total_and_hierarchy(captured):
    n = ingest_fidc_setor(None, [_tab_ii()])

    assert n == 1
    assert captured["table"] == "cvm_fidc_setor"
    assert captured["conflict"] == "cnpj,period"
    (r,) = captured["rows"]
    assert r["cnpj"] == "05754060000113"
    assert r["period"] == date(2026, 7, 31)
    assert r["vl_carteira"] == 1403730252.03
    assert r["vl_d_serv"] == 1403730252.03
    assert r["vl_d1_serv"] == 1403730252.03
    assert r["vl_a_indust"] == 0.0
    assert r["vl_k_marca"] == 0.0
    # only the unmodeled columns survive in raw
    assert set(r["raw"]) == {"TP_FUNDO_CLASSE", "DENOM_SOCIAL"}


def test_setor_map_names_every_tab_ii_value_column():
    modeled = {_setor.FIELD_MAP[c][0][0] for c in _setor.FIELD_MAP if c.startswith("vl_")}
    assert modeled == {"TAB_II_VL_CARTEIRA", "TAB_II_D_VL_SERV", "TAB_II_D1_VL_SERV", *_TAB_II_ZERO_COLS}


def test_setor_header_drift_raises():
    row = _tab_ii()
    row["DATA_COMPETENCIA"] = row.pop("DT_COMPTC")
    with pytest.raises(FieldMapMismatch):
        ingest_fidc_setor(None, [row])


# ---------------------------------------------------------------------------
# tab_X — SCR grade ladder
# ---------------------------------------------------------------------------

def test_scr_two_ladders_and_tax_debt(captured):
    n = ingest_fidc_scr(None, [_tab_x()])

    assert n == 1
    assert captured["table"] == "cvm_fidc_scr"
    assert captured["conflict"] == "cnpj,period"
    (r,) = captured["rows"]
    assert r["vl_devedor_aa"] == 1403730252.03
    assert r["vl_oper_aa"] == 1403730252.03
    assert r["vl_devedor_h"] == 0.0
    assert r["vl_oper_h"] == 0.0
    assert r["vl_debito_tribut"] == 0.0
    assert set(r["raw"]) == {"TP_FUNDO_CLASSE", "DENOM_SOCIAL"}


def test_scr_map_covers_nine_grades_twice():
    dev = [c for c in _scr.FIELD_MAP if c.startswith("vl_devedor_")]
    ope = [c for c in _scr.FIELD_MAP if c.startswith("vl_oper_")]
    assert len(dev) == 9 and len(ope) == 9


# ---------------------------------------------------------------------------
# cvm_fidc_mensal.vl_total — filled from tab_II, never guessed
# ---------------------------------------------------------------------------

def _tab_iv(**over):
    row = dict(_KEY)
    row["TAB_IV_A_VL_PL"] = "1400000000.00"
    row["TAB_IV_B_VL_PL_MEDIO"] = "1390000000.00"
    row.update(over)
    return row


def test_mensal_vl_total_is_filled_from_tab_ii(captured):
    ingest_fidc_mensal(None, [_tab_iv()], rows_vi=[], rows_ii=[_tab_ii()])
    (r,) = captured["rows"]
    assert captured["table"] == "cvm_fidc_mensal"
    assert r["vl_patrim_liq"] == 1400000000.0
    assert r["vl_total"] == 1403730252.03


def test_mensal_vl_total_stays_null_without_tab_ii(captured):
    ingest_fidc_mensal(None, [_tab_iv()], rows_vi=[], rows_ii=None)
    (r,) = captured["rows"]
    assert r["vl_total"] is None


def test_mensal_vl_total_matches_on_fund_and_period_only(captured):
    other = _tab_ii(CNPJ_FUNDO_CLASSE="11.003.181/0001-26", TAB_II_VL_CARTEIRA="1.00")
    ingest_fidc_mensal(None, [_tab_iv()], rows_vi=[], rows_ii=[other])
    (r,) = captured["rows"]
    assert r["vl_total"] is None


# ---------------------------------------------------------------------------
# era routing
# ---------------------------------------------------------------------------

def test_each_tab_is_backfilled_only_from_its_first_published_month():
    from src.pipeline.cvm_pipeline import _FIDC_TAB_FIRST_PERIOD, _iter_month_pairs

    assert _FIDC_TAB_FIRST_PERIOD == {
        "i": date(2019, 11, 1), "ii": date(2013, 1, 1),
        "viii": date(2013, 1, 1), "x": date(2023, 10, 1),
        "x7": date(2019, 11, 1),  # tab_X_7, migration 45
    }
    years = list(range(2013, 2027))
    today = date(2026, 9, 16)
    x_months = _iter_month_pairs(years, today, available_from=_FIDC_TAB_FIRST_PERIOD["x"])
    assert x_months[0] == (2023, 10)
    assert (2023, 9) not in x_months
    i_months = _iter_month_pairs(years, today, available_from=_FIDC_TAB_FIRST_PERIOD["i"])
    assert i_months[0] == (2019, 11)
    assert (2019, 10) not in i_months
    viii_months = _iter_month_pairs(years, today, available_from=_FIDC_TAB_FIRST_PERIOD["viii"])
    assert viii_months[0] == (2013, 1)


def test_fidc_tab_doc_type_flips_between_hist_and_monthly():
    from src.pipeline.cvm_pipeline import _fidc_tab_doc_type

    assert _fidc_tab_doc_type("viii", 2024) == "hist_mensal_tab_viii"
    assert _fidc_tab_doc_type("viii", 2025) == "mensal_tab_viii"
    assert _fidc_tab_doc_type("i", 2013) == "hist_mensal_tab_i"
    assert _fidc_tab_doc_type("x", 2026) == "mensal_tab_x"


def test_every_fidc_tab_doc_type_exists_in_config():
    from src.fetchers.cvm_config import DatasetConfig
    from src.pipeline.cvm_pipeline import _fidc_tab_doc_type

    for tab, member in (("i", "tab_I_"), ("ii", "tab_II_"), ("viii", "tab_VIII_"), ("x", "tab_X_")):
        for year in (2024, 2025):
            cfg = DatasetConfig.get_dataset_config("fidc", _fidc_tab_doc_type(tab, year))
            assert member in cfg["csv_name_pattern"]
            assert cfg["csv_name_pattern"].endswith("{year}{month:02d}.csv")
