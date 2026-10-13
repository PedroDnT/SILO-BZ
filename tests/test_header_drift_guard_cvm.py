"""The header-drift guard on the CVM ingests that lacked it (#879).

`assert_map_matches` raises FieldMapMismatch when a FIELD_MAP column the ingest
cannot do without has no candidate left in the source header. Each case below
takes a real CVM file from the #881 fixtures (tests/fixtures/, see
test_raw_file_fixtures_cvm.py for their provenance), renames one key column in
every row, as a CVM rename would, and expects the ingest to raise before it
writes anything. The unrenamed files are ingested by test_raw_file_fixtures_cvm.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from src.fetchers.cia_fetcher import CIAFetcher
from src.fetchers.cvm_fetcher import CVMFetcher
from src.parsers.field_maps import (
    cia_account,
    cia_company,
    cia_event,
    cia_fca_valor_mobiliario,
    cia_filing,
    fi_cda,
    fi_cda_acoes,
    fi_cda_cotas,
    fi_cda_debentures,
    fidc_tranche,
    fidc_tranche_flows,
    fip_periodic,
    fii_periodic,
    fund_registry,
)
from src.parsers.mapping import FieldMapMismatch, map_coverage
from src.pipeline import ingest_cia, ingest_etf, ingest_fi, ingest_fidc, ingest_fii, ingest_misc
from tests.test_raw_file_fixtures_cvm import FX, _fetch, _payload


def _rename(rows: List[Dict[str, Any]], old: str) -> List[Dict[str, Any]]:
    new = old + "_RENOMEADO"
    return [{(new if k == old else k): v for k, v in r.items()} for r in rows]


def _header(rows):
    return set().union(*(r.keys() for r in rows))


def _assert_renamed_away(rows, renamed, old, field_map, column):
    """The fixture held `old`, and after the rename `column` has no candidate."""
    assert old in _header(rows), f"fixture lacks {old}"
    assert column in map_coverage(_header(renamed), field_map).unmatched, (
        f"another candidate for {column} is still in the header"
    )


def _no_writes(module):
    boom = AssertionError("the guard must raise before any write")
    return (
        patch.object(module, "upsert_rows", side_effect=boom),
        patch.object(module, "replace_scoped_rows", side_effect=boom, create=True),
    )


def _expect_raise(module, call: Callable[[], Any]):
    p1, p2 = _no_writes(module)
    with p1, p2, pytest.raises(FieldMapMismatch):
        call()


# ------------------------------------------------------------- loaders
def _cda(blc, doc_type):
    return _fetch("fi", doc_type, 2026, 6, [FX / f"cvm_fi_cda/cda_fi_BLC_{blc}_202606.csv"])


def _cad():
    return _fetch("fi", "cad", None, None, [FX / "cvm_fi_cad/cad_fi.csv"], zipped=False)


def _fidc(tab):
    doc = "mensal_tab_" + tab.lower().replace("_", "")
    return _fetch("fidc", doc, 2026, 8, [FX / f"cvm_fidc_tranche/inf_mensal_fidc_tab_{tab}_202608.csv"])


# One case per ingest: (fixture loader, header to rename, field map, column it
# feeds, the ingest call on the renamed rows).
CASES = {
    "cda_block1": (
        lambda: _cda(1, "cda"), "DT_COMPTC", fi_cda.FIELD_MAP, "period",
        lambda rows: ingest_fi.ingest_fi_cda(object(), rows, 2026, 6), ingest_fi,
    ),
    "cda_block2": (
        lambda: _cda(2, "cda_cotas"), "CNPJ_FUNDO_CLASSE_COTA", fi_cda_cotas.FIELD_MAP, "cnpj_cota",
        lambda rows: ingest_fi.ingest_fi_cda_cotas(object(), rows, 2026, 6), ingest_fi,
    ),
    "cda_block4": (
        lambda: _cda(4, "cda_acoes"), "CD_ATIVO", fi_cda_acoes.FIELD_MAP, "cd_ativo",
        lambda rows: ingest_fi.ingest_fi_cda_acoes(object(), rows, 2026, 6), ingest_fi,
    ),
    "cda_block6": (
        lambda: _cda(6, "cda_debentures"), "CPF_CNPJ_EMISSOR", fi_cda_debentures.FIELD_MAP,
        "cpf_cnpj_emissor",
        lambda rows: ingest_fi.ingest_fi_cda_debentures(object(), rows, 2026, 6), ingest_fi,
    ),
    "cad_fi": (
        _cad, "CNPJ_FUNDO", fund_registry.FIELD_MAP, "cnpj",
        lambda rows: ingest_fi.ingest_fund_registry_fi(object(), rows), ingest_fi,
    ),
    "etf_registry": (
        _cad, "CNPJ_FUNDO", ingest_etf._CAD_GUARD_MAP, "cnpj",
        lambda rows: ingest_etf.ingest_etf_registry(object(), ingest_etf.load_etf_seed(), rows),
        ingest_etf,
    ),
    "fidc_tranche_flows": (
        lambda: _fidc("X_4"), "TAB_X_TP_OPER", fidc_tranche_flows.FIELD_MAP, "tp_oper",
        lambda rows: ingest_fidc.ingest_fidc_tranche_flows(object(), rows), ingest_fidc,
    ),
    "fip": (
        lambda: _fetch("fip", "inf_quadrimestral", 2025, None,
                       [FX / "cvm_fip/inf_quadrimestral_fip_2025.csv"], zipped=False),
        "DT_COMPTC", fip_periodic.FIELD_MAP, "period",
        lambda rows: ingest_misc.ingest_fip_periodic(object(), rows, "inf_quadrimestral", 2025),
        ingest_misc,
    ),
    "fii_anual": (
        lambda: _fetch("fii", "anual", 2025, None, [FX / "cvm_fii_periodic/inf_anual_fii_geral_2025.csv"]),
        "Data_Referencia", fii_periodic.FIELD_MAP, "data_referencia",
        lambda rows: ingest_fii.ingest_fii_periodic(object(), rows, "anual", 2025), ingest_fii,
    ),
    "fii_dfin": (
        lambda: _fetch("fii", "dfin", 2025, None, [FX / "cvm_fii_periodic/dfin_fii_2025.csv"], zipped=False),
        "Data_Referencia", fii_periodic.FIELD_MAP, "data_referencia",
        lambda rows: ingest_fii.ingest_fii_periodic(object(), rows, "dfin", 2025), ingest_fii,
    ),
    "cia_company": (
        lambda: _fetch("cia_aberta", "cad", None, None, [FX / "cvm_cia/cad_cia_aberta.csv"], zipped=False),
        "CD_CVM", cia_company.FIELD_MAP, "cd_cvm",
        lambda rows: ingest_cia.ingest_cia_company(object(), rows), ingest_cia,
    ),
    "cia_event": (
        lambda: _fetch("cia_aberta", "ipe", 2026, None, [FX / "cvm_cia/ipe_cia_aberta_2026.csv"]),
        "Protocolo_Entrega", cia_event.FIELD_MAP, "protocolo",
        lambda rows: ingest_cia.ingest_cia_event(object(), rows), ingest_cia,
    ),
    "cia_ticker": (
        lambda: _fetch("cia_aberta", "fca_valor_mobiliario", 2026, None,
                       [FX / "cvm_cia/fca_cia_aberta_valor_mobiliario_2026.csv"]),
        "Data_Referencia", cia_fca_valor_mobiliario.FIELD_MAP, "data_refer",
        lambda rows: ingest_cia.ingest_cia_ticker(object(), rows), ingest_cia,
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_renamed_key_column_raises_before_any_write(case):
    load, old, field_map, column, call, module = CASES[case]
    rows = load()
    renamed = _rename(rows, old)
    _assert_renamed_away(rows, renamed, old, field_map, column)
    _expect_raise(module, lambda: call(renamed))


@pytest.mark.parametrize("tab", ["X_2", "X_3", "X_6"])
def test_fidc_tranche_raises_when_any_joined_tab_loses_the_join_key(tab):
    tabs = {t: _fidc(t) for t in ("X_2", "X_3", "X_6")}
    renamed = _rename(tabs[tab], "TAB_X_CLASSE_SERIE")
    _assert_renamed_away(tabs[tab], renamed, "TAB_X_CLASSE_SERIE", fidc_tranche.FIELD_MAP, "classe_serie")
    tabs[tab] = renamed
    _expect_raise(ingest_fidc, lambda: ingest_fidc.ingest_fidc_tranche(
        object(), tabs["X_2"], tabs["X_3"], tabs["X_6"], 2026, 8))


def _itr_members():
    names = ("itr_cia_aberta_2026.csv", "itr_cia_aberta_DRE_con_2026.csv", "itr_cia_aberta_BPA_con_2026.csv")
    body = _payload([FX / "cvm_cia" / n for n in names], zipped=True)
    with patch.object(CVMFetcher, "_download", AsyncMock(return_value=body)):
        return CIAFetcher().fetch_zip_members("itr", 2026, include_summary=True)


def test_cia_filing_summary_raises_on_a_renamed_dt_refer():
    summary = _itr_members()[0]
    assert summary.grupo == "_summary"
    renamed = _rename(summary.rows, "DT_REFER")
    _assert_renamed_away(summary.rows, renamed, "DT_REFER", cia_filing.FIELD_MAP, "dt_refer")
    _expect_raise(ingest_cia, lambda: ingest_cia.ingest_cia_filing(object(), renamed, "itr"))


def test_cia_account_raises_before_any_member_lands():
    """The drifted member is the LAST one: the BPA member before it is valid,
    and must not be upserted before the DRE header is found wrong."""
    members = [m for m in _itr_members() if m.is_account_data]
    assert [m.grupo for m in members] == ["BPA", "DRE"]
    dre = members[1]
    renamed = _rename(dre.rows, "CD_CONTA")
    _assert_renamed_away(dre.rows, renamed, "CD_CONTA", cia_account.FIELD_MAP, "cd_conta")
    members[1] = dataclasses.replace(dre, rows=renamed)
    _expect_raise(ingest_cia, lambda: ingest_cia.ingest_cia_account(object(), members, "itr"))
