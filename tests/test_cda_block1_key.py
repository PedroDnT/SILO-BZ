"""CDA block 1 (cvm_fi_cda) keeps one row per government bond — issue #348.

upsert_rows dedupes rows that share a conflict-key tuple, last write wins, with
no error. Block 1's old key (cnpj, period, tp_aplic, tp_ativo) stopped at a
column that reads "Título público federal" for every bond, so a fund holding an
LFT, an NTN-B and an LTN kept one of them. These tests pin that every source
row survives the key, on the shapes that broke it.
"""

import re
from datetime import date
from pathlib import Path

from src.parsers.field_maps import fi_cda as _cda

ROOT = Path(__file__).resolve().parents[1]


def _bond(isin, titpub, venc, negoc="Para negociação", tp_fundo="CLASSES - FIF",
          cnpj="00.102.322/0001-41", vl="1000.00"):
    """One row as CVM's cda_fi_BLC_1_YYYYMM.csv ships it (2023+ headers)."""
    return {
        "TP_FUNDO_CLASSE": tp_fundo, "CNPJ_FUNDO_CLASSE": cnpj,
        "DENOM_SOCIAL": "FUNDO TESTE", "DT_COMPTC": "2026-08-31",
        "TP_APLIC": "Títulos Públicos", "TP_ATIVO": "Título público federal",
        "EMISSOR_LIGADO": "", "TP_NEGOC": negoc,
        "QT_VENDA_NEGOC": "0.000000", "VL_VENDA_NEGOC": "0.00",
        "QT_AQUIS_NEGOC": "0.000000", "VL_AQUIS_NEGOC": "0.00",
        "QT_POS_FINAL": "80.000000", "VL_MERC_POS_FINAL": vl,
        "VL_CUSTO_POS_FINAL": vl, "DT_CONFID_APLIC": "",
        "TP_TITPUB": titpub, "CD_ISIN": isin, "CD_SELIC": "760199",
        "DT_EMISSAO": "2010-02-10", "DT_VENC": venc,
    }


# Real ISINs from the 202608 file: two LFT maturities and one NTN-B, all under
# the same fund, month, application type and asset type.
ONE_FUND = [
    _bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01"),
    _bond("BRSTNCLF1RL5", "LETRAS FINANCEIRAS DO TESOURO", "2029-03-01"),
    _bond("BRSTNCNTB3D4", "NOTAS DO TESOURO NACIONAL SERIE B", "2050-08-15"),
    # Same bond held under a second trading intent: a separate position.
    _bond("BRSTNCNTB3D4", "NOTAS DO TESOURO NACIONAL SERIE B", "2050-08-15",
          negoc="Mantido até o vencimento"),
]


def _captured(monkeypatch, rows, year=2026, month=8):
    from src.pipeline.ingest_fi import ingest_fi_cda

    seen = {}

    def fake_upsert(conn, table, recs, **kw):
        seen["table"], seen["rows"], seen["conflict"] = table, recs, kw["conflict_columns"]
        return len(recs)

    monkeypatch.setattr("src.pipeline.ingest_fi.upsert_rows", fake_upsert)
    ingest_fi_cda(object(), rows, year, month)
    return seen


def _keys(seen):
    cols = seen["conflict"].split(",")
    return {tuple(r[c] for c in cols) for r in seen["rows"]}


def test_every_bond_of_one_fund_survives_the_key(monkeypatch):
    seen = _captured(monkeypatch, ONE_FUND)
    assert seen["table"] == "cvm_fi_cda"
    assert len(seen["rows"]) == len(ONE_FUND)
    assert len(_keys(seen)) == len(ONE_FUND), (
        "rows share a conflict key, so upsert_rows would keep only the last"
    )


def test_the_2005_fi_and_fif_filings_with_different_values_keep_both(monkeypatch):
    """HIST 2005 has 144 CNPJs filed as both FI and FIF with the same bond."""
    rows = [
        {**_bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01",
                 vl="10.00"), "DT_COMPTC": "2005-06-30"},
        {**_bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01",
                 tp_fundo="FIF", vl="20.00"), "DT_COMPTC": "2005-06-30"},
    ]
    for r in rows:  # the yearly HIST layout uses the pre-CVM-175 headers
        r["TP_FUNDO"] = r.pop("TP_FUNDO_CLASSE")
        r["CNPJ_FUNDO"] = r.pop("CNPJ_FUNDO_CLASSE")
    rows[0]["TP_FUNDO"] = "FI"
    seen = _captured(monkeypatch, rows, year=2005, month=None)
    assert len(_keys(seen)) == 2


def test_the_bond_is_typed_not_left_in_raw(monkeypatch):
    seen = _captured(monkeypatch, ONE_FUND[2:3])
    r = seen["rows"][0]
    assert r["cd_isin"] == "BRSTNCNTB3D4"
    assert r["tp_titpub"] == "NOTAS DO TESOURO NACIONAL SERIE B"
    assert r["dt_venc"] == date(2050, 8, 15)
    assert r["tp_fundo"] == "CLASSES - FIF"
    assert r["tp_negoc"] == "Para negociação"
    assert float(r["qt_pos_final"]) == 80.0


def _constraint_cols(sql, name):
    # NULLS DISTINCT, like the key it replaced: 1,705 legacy FIIM rows carry
    # NULL key parts and would collide otherwise (migration 49 header).
    m = re.search(rf"CONSTRAINT {name}\s+UNIQUE\s*\(([^)]*)\)", sql)
    assert m, f"{name} not declared UNIQUE (NULLS DISTINCT)"
    return tuple(c.strip() for c in m.group(1).split(","))


def test_field_map_schema_and_migration_agree_on_the_key():
    """ON CONFLICT resolves only against a unique index on exactly these columns."""
    schema = (ROOT / "src/store/schema.sql").read_text()
    migration = (ROOT / "src/store/migrations/49_cda_block1_key.sql").read_text()
    assert _constraint_cols(schema, "uq_fi_cda") == _cda.CONFLICT
    assert _constraint_cols(migration, "uq_fi_cda") == _cda.CONFLICT
    assert set(_cda.CONFLICT) <= set(_cda.FIELD_MAP)


def test_the_migration_backfills_every_year_it_can_hold():
    """A year without a backfill statement keeps NULL keys, and the refill of
    that year would then insert beside the surviving row instead of merging."""
    migration = (ROOT / "src/store/migrations/49_cda_block1_key.sql").read_text()
    years = {int(y) for y in re.findall(r"period >= DATE '(\d{4})-01-01'", migration)}
    assert years == set(range(2005, 2027))


def test_an_identical_twin_under_two_labels_is_kept_once(monkeypatch):
    """202503: 33 positions filed as both FI and CLASSES - FIF, identical
    otherwise. Both rows would double the position in every sum."""
    rows = [_bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01", tp_fundo="FI"),
            _bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01")]
    seen = _captured(monkeypatch, rows)
    assert [r["tp_fundo"] for r in seen["rows"]] == ["CLASSES - FIF"]


def test_twins_with_different_positions_both_survive(monkeypatch):
    """HIST 2005: 16 FI/FIF groups carry different values, so they are two
    real positions and neither may be dropped."""
    rows = [_bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01", tp_fundo="FI", vl="10.00"),
            _bond("BRSTNCLF1RK7", "LETRAS FINANCEIRAS DO TESOURO", "2028-09-01", tp_fundo="FIF", vl="20.00")]
    seen = _captured(monkeypatch, rows)
    assert sorted(r["tp_fundo"] for r in seen["rows"]) == ["FI", "FIF"]
