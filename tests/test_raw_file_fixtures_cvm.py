"""Real CVM files, trimmed, parsed end to end (#881).

Until these fixtures existed, the CVM families below were tested only with
inline rows, so a change in CVM's file format reached CI only if a header guard
happened to catch it at run time. Each test here feeds a trimmed copy of a real
CVM file through the production path:

    CVMFetcher.fetch (URL, zip member selection by the real csv_name_pattern,
    latin-1 decode, CSV parse)  ->  the ingest_* function and its field map
    ->  upsert_rows / replace_scoped_rows (patched to capture the records)

and asserts the row count, the exact set of natural keys and the field map's
header coverage. Expected values are literals read off the fixture by hand,
never computed by the code under test.

Provenance. Every fixture is the source's own bytes (latin-1, CRLF), cut from a
file downloaded from https://dados.cvm.gov.br/dados/ on 2026-10-13 at 08:37
UTC-3 (11:37 UTC). A cut keeps the header line and whole data lines only; the
cutting script checked that every kept line parses to exactly one record with
the header's column count, so no quoted field was split. The file name is the
real zip member name (or the real file name for a plain CSV).

  cvm_fi_cda/cda_fi_BLC_{1,2,4,6}_202606.csv
      FI/DOC/CDA/DADOS/cda_fi_202606.zip, members of the same name;
      header + first 10 lines each.
  cvm_fi_cad/cad_fi.csv
      FI/CAD/DADOS/cad_fi.csv; header + first 10 lines + every line of the
      three ETF CNPJs of src/store/seeds/etf_registry_seed.csv that appear
      first in the file (11184136000115, 40955945000181, 43955479000122).
  cvm_fidc_tranche/inf_mensal_fidc_tab_X_{2,3,4,6}_202608.csv
      FIDC/DOC/INF_MENSAL/DADOS/inf_mensal_fidc_202608.zip; header + every line
      of the first three funds of tab X_2 (05754060000113, 06018364000185,
      06081379000198) in each tab.
  cvm_fip/inf_quadrimestral_fip_2025.csv
      FIP/DOC/INF_QUADRIMESTRAL/DADOS/inf_quadrimestral_fip_2025.csv;
      header + first 10 lines.
  cvm_fii_periodic/inf_anual_fii_geral_2025.csv
      FII/DOC/INF_ANUAL/DADOS/inf_anual_fii_2025.zip, member of the same name;
      header + first 8 lines.
  cvm_fii_periodic/dfin_fii_2025.csv
      FII/DOC/DFIN/DADOS/dfin_fii_2025.csv; header + first 10 lines.
  cvm_cia/cad_cia_aberta.csv
      CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv; header + first 10 lines + both
      lines of CD_CVM 25283, the first company CVM lists under two markets.
  cvm_cia/ipe_cia_aberta_2026.csv
      CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_2026.zip; header + first 10 lines.
  cvm_cia/fca_cia_aberta_valor_mobiliario_2026.csv
      CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_2026.zip, member of the same
      name; header + first 10 lines.
  cvm_cia/itr_cia_aberta_2026.csv, itr_cia_aberta_{BPA,DRE}_con_2026.csv
      CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip, members of the same
      name; header + first 6 lines (summary) and first 12 lines (statements).
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
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
from src.parsers.mapping import map_coverage
from src.pipeline import ingest_cia, ingest_etf, ingest_fi, ingest_fidc, ingest_fii, ingest_misc

FX = Path(__file__).resolve().parent / "fixtures"

NEW_FIXTURE_DIRS = (
    "cvm_fi_cda",
    "cvm_fi_cad",
    "cvm_fidc_tranche",
    "cvm_fip",
    "cvm_fii_periodic",
    "cvm_cia",
)


# --------------------------------------------------------------------- helpers
def _payload(paths: List[Path], zipped: bool) -> bytes:
    """What the CVM URL serves: the plain CSV, or a zip holding the members."""
    if not zipped:
        assert len(paths) == 1
        return paths[0].read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in paths:
            zf.writestr(p.name, p.read_bytes())
    return buf.getvalue()


def _fetch(entity, doc_type, year, month, paths, zipped=True) -> List[Dict[str, Any]]:
    """CVMFetcher.fetch with only the HTTP download replaced by the fixture."""
    body = _payload(paths, zipped)
    with patch.object(CVMFetcher, "_download", AsyncMock(return_value=body)):
        return asyncio.run(CVMFetcher().fetch(entity, doc_type, year, month))


def _ingest(module, fn, *args):
    """Run an ingest function; return (its result, {table: [records]})."""
    captured: Dict[str, List[Dict[str, Any]]] = {}

    def _fake(conn, table, recs, **kw):
        captured.setdefault(table, []).extend(recs)
        return len(recs)

    with patch.object(module, "upsert_rows", side_effect=_fake), patch.object(
        module, "replace_scoped_rows", side_effect=_fake, create=True
    ):
        n = fn(object(), *args)
    return n, captured


def _keys(records, columns):
    return [tuple(r.get(c) for c in columns) for r in records]


def _unmatched(rows, field_map):
    header = set().union(*(r.keys() for r in rows))
    return set(map_coverage(header, field_map).unmatched)


def test_every_new_fixture_is_under_50_kb():
    files = [p for d in NEW_FIXTURE_DIRS for p in (FX / d).iterdir()]
    assert len(files) == 18
    for p in files:
        assert p.stat().st_size < 50_000, p


def test_fixtures_are_the_sources_latin1_crlf_bytes():
    for d in NEW_FIXTURE_DIRS:
        for p in (FX / d).iterdir():
            b = p.read_bytes()
            assert b.endswith(b"\r\n") and b.count(b"\n") == b.count(b"\r\n"), p
            with pytest.raises(UnicodeDecodeError):
                b.decode("utf-8")          # an accented letter in latin-1, not UTF-8


# ------------------------------------------------------------------ FI CDA
JUN = date(2026, 6, 1)
FIF = "CLASSES - FIF"
TP = "Títulos Públicos"
TPF = "Título público federal"
COMPR = "Operações Compromissadas"
NEG = "Para negociação"


def _cda(blc, doc_type, fn):
    rows = _fetch("fi", doc_type, 2026, 6, [FX / f"cvm_fi_cda/cda_fi_BLC_{blc}_202606.csv"])
    return rows, _ingest(ingest_fi, fn, rows, 2026, 6)


def test_cda_block1_monthly_file():
    rows, (n, cap) = _cda(1, "cda", ingest_fi.ingest_fi_cda)
    assert len(rows) == 10 and n == 10
    assert _unmatched(rows, fi_cda.FIELD_MAP) == set()
    assert set(_keys(cap["cvm_fi_cda"], fi_cda.CONFLICT)) == {
        ("00017024000153", JUN, FIF, TP, TPF, "BRSTNCLF1RH3", NEG),
        ("00017024000153", JUN, FIF, TP, TPF, "BRSTNCLF1RG5", NEG),
        ("00017024000153", JUN, FIF, TP, TPF, "BRSTNCLF1RI1", NEG),
        ("00073041000108", JUN, FIF, COMPR, TPF, "BRSTNCLF1RX0", NEG),
        ("00073041000108", JUN, FIF, TP, TPF, "BRSTNCLF1RG5", NEG),
        ("00073041000108", JUN, FIF, TP, TPF, "BRSTNCLF1RL5", NEG),
        ("00083181000167", JUN, FIF, TP, TPF, "BRSTNCLF1RU6", NEG),
        ("00089915000115", JUN, FIF, COMPR, TPF, "BRSTNCNTB4X0", NEG),
        ("00102322000141", JUN, FIF, COMPR, TPF, "BRSTNCNTB7Y1", NEG),
        ("00194256000187", JUN, FIF, COMPR, TPF, "BRSTNCLTN8J8", NEG),
    }
    # DENOM_SOCIAL leaves the holding rows for cvm_fi_cda_fund_name, once per fund.
    names = cap["cvm_fi_cda_fund_name"]
    assert len(names) == 6
    assert {r["cnpj"] for r in names} == {k[0] for k in _keys(cap["cvm_fi_cda"], fi_cda.CONFLICT)}
    assert all("DENOM_SOCIAL" not in r["raw"] for r in cap["cvm_fi_cda"])
    first = cap["cvm_fi_cda"][0]
    assert first["qt_pos_final"] == 29.0 and first["vl_merc_pos_final"] == 560284.51


def test_cda_block2_fund_quotas():
    rows, (n, cap) = _cda(2, "cda_cotas", ingest_fi.ingest_fi_cda_cotas)
    assert len(rows) == 10 and n == 10
    assert _unmatched(rows, fi_cda_cotas.FIELD_MAP) == set()
    cotas = "Cotas de Fundos"
    assert set(_keys(cap["cvm_fi_cda_cotas"], fi_cda_cotas.CONFLICT)) == {
        ("00068305000135", JUN, FIF, "01165780000192", cotas, None),
        ("00071477000168", JUN, FIF, "27146328000177", cotas, None),
        *(
            ("00083181000167", JUN, FIF, held, cotas, None)
            for held in (
                "42273290000197", "01235622000161", "10522648000181", "41833876000104",
                "35360651000177", "10597218000129", "08277553000106", "18697172000121",
            )
        ),
    }
    assert len(cap["cvm_fi_cda_fund_name"]) == 3


def test_cda_block4_equities():
    rows, (n, cap) = _cda(4, "cda_acoes", ingest_fi.ingest_fi_cda_acoes)
    assert len(rows) == 10 and n == 10
    assert _unmatched(rows, fi_cda_acoes.FIELD_MAP) == set()
    deb = ("Debêntures", "Debênture simples")
    assert set(_keys(cap["cvm_fi_cda_acoes"], fi_cda_acoes.CONFLICT)) == {
        ("00102322000141", JUN, FIF, "Ações", "Ação ordinária", "ITUB3", NEG),
        *(
            ("00322699000106", JUN, FIF, *deb, ticker, NEG)
            for ticker in (
                "AURE13", "CIEL18", "VBBR24", "VBBR15", "VVRT11",
                "TAEEF1", "TAEEE1", "TAEEA5", "TOTS16",
            )
        ),
    }
    assert len(cap["cvm_fi_cda_fund_name"]) == 2


def test_cda_block6_debentures():
    rows, (n, cap) = _cda(6, "cda_debentures", ingest_fi.ingest_fi_cda_debentures)
    assert len(rows) == 10 and n == 10
    assert _unmatched(rows, fi_cda_debentures.FIELD_MAP) == set()
    recs = cap["cvm_fi_cda_debentures"]
    key_wo_hash = [c for c in fi_cda_debentures.CONFLICT if c != "row_hash"]
    cra = ("Títulos ligados ao agronegócio", "CRA")
    fund = ("00807777000162", JUN, FIF)
    assert set(_keys(recs, key_wo_hash)) == {
        (*fund, "Debêntures", "Debênture simples", "01.599.101/0001-93", date(2027, 12, 31), NEG),
        (*fund, *cra, "46.059.783/0001-80", date(2028, 7, 5), NEG),
        (*fund, *cra, "10.753.164/0001-43", date(2029, 9, 5), NEG),
        (*fund, *cra, "25.005.683/0001-09", date(2034, 2, 10), NEG),
        (*fund, *cra, "08.769.451/0001-08", date(2029, 4, 12), NEG),
        (*fund, *cra, "10.753.164/0001-43", date(2030, 8, 15), NEG),
        (*fund, *cra, "10.753.164/0001-43", date(2027, 8, 16), NEG),
        (*fund, *cra, "02.773.542/0001-22", date(2026, 12, 17), NEG),
        (*fund, *cra, "09.304.427/0001-58", date(2032, 12, 23), NEG),
        (*fund, *cra, "01.838.723/0001-27", date(2030, 7, 15), NEG),
    }
    hashes = {r["row_hash"] for r in recs}
    assert len(hashes) == 10 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
    # Block 6 keeps the fund name in raw: it has no fund-name table write.
    assert "cvm_fi_cda_fund_name" not in cap


# --------------------------------------------------------------- FI cad_fi
CAD_CNPJS = [
    "00000684000121", "00000731000137", "00000732000181", "00000740000128",
    "00000749000139", "00000756000130", "00000759000174", "00000765000121",
    "00000777000156", "00016903000160",
    "11184136000115", "40955945000181", "43955479000122",
]


def _cad_rows():
    return _fetch("fi", "cad", None, None, [FX / "cvm_fi_cad/cad_fi.csv"], zipped=False)


def test_cad_fi_registry():
    rows = _cad_rows()
    n, cap = _ingest(ingest_fi, ingest_fi.ingest_fund_registry_fi, rows)
    assert len(rows) == 13 and n == 13
    assert _unmatched(rows, fund_registry.FIELD_MAP) == set()
    recs = cap["cvm_fund_registry"]
    assert _keys(recs, fund_registry.CONFLICT) == [(c, "fi") for c in CAD_CNPJS]
    first = recs[0]
    assert first["status"] == "CANCELADA" and first["is_active"] is False


def test_etf_registry_enriches_from_the_real_cad_rows():
    seed = ingest_etf.load_etf_seed()
    n, cap = _ingest(ingest_etf, ingest_etf.ingest_etf_registry, seed, _cad_rows())
    recs = {r["ticker"]: r for r in cap["cvm_etf_registry"]}
    assert n == len(recs) == len(seed)
    # The three seed ETFs present in the fixture take cad_fi's registration date;
    # the seed's status wins (#899: GOVE11 is CANCELADA in cad_fi, active in the
    # CVM-175 seed and still trading). A seed ETF absent from it keeps NULL enrichment.
    assert {t: (recs[t]["cnpj"], recs[t]["dt_reg"], recs[t]["situacao"]) for t in ("GOVE11", "URET11", "GURU11")} == {
        "GOVE11": ("11184136000115", date(2009, 12, 14), "Em Funcionamento Normal"),
        "URET11": ("40955945000181", date(2021, 12, 27), "CANCELADA"),
        "GURU11": ("43955479000122", date(2021, 12, 3), "CANCELADA"),
    }
    assert (recs["GOVE11"]["is_active"], recs["GOVE11"]["dt_cancel"]) == (True, None)
    assert recs["URET11"]["is_active"] is False and recs["GURU11"]["is_active"] is False
    assert recs["URET11"]["admin"] == "BANCO BNP PARIBAS BRASIL S/A"
    assert recs["GURU11"]["admin"] == "BTG PACTUAL SERVIÇOS FINANCEIROS S/A DTVM"
    enriched = {t for t, r in recs.items() if r["dt_reg"] is not None}
    assert enriched == {"GOVE11", "URET11", "GURU11"}


# ------------------------------------------------------- FIDC tranche/flows
AUG31 = date(2026, 8, 31)
SEN1 = "Subclasse Senior Subclasse 1"
SUB = "Subclasse Subordinada  |"          # the source's own spacing and pipe
TRANCHE_KEYS = {
    ("05754060000113", AUG31, SEN1),
    ("05754060000113", AUG31, SUB),
    ("06018364000185", AUG31, "Subclasse Senior Série 1"),
    ("06018364000185", AUG31, "Subclasse Subordinada Subordinada 1 |"),
    ("06081379000198", AUG31, SEN1),
    ("06081379000198", AUG31, SUB),
}


def _fidc(tab):
    doc = "mensal_tab_" + tab.lower().replace("_", "")
    return _fetch("fidc", doc, 2026, 8, [FX / f"cvm_fidc_tranche/inf_mensal_fidc_tab_{tab}_202608.csv"])


def test_fidc_tranche_joins_x2_x3_x6():
    x2, x3, x6 = _fidc("X_2"), _fidc("X_3"), _fidc("X_6")
    assert (len(x2), len(x3), len(x6)) == (6, 6, 5)
    assert _unmatched(x2 + x3 + x6, fidc_tranche.FIELD_MAP) == set()
    n, cap = _ingest(ingest_fidc, ingest_fidc.ingest_fidc_tranche, x2, x3, x6, 2026, 8)
    recs = cap["cvm_fidc_tranche"]
    assert n == 6
    assert set(_keys(recs, fidc_tranche.CONFLICT)) == TRANCHE_KEYS
    by_key = {k: r for k, r in zip(_keys(recs, fidc_tranche.CONFLICT), recs)}
    # One row carries a column from each of the three tabs.
    caterpillar = by_key[("05754060000113", AUG31, SEN1)]
    assert caterpillar["qt_cota"] == 27809423.4357832      # X_2
    assert caterpillar["vl_rentab_mes"] == 1.43            # X_3
    assert caterpillar["pr_desemp_real"] == 1.43           # X_6
    # X_6 has no line for this tranche; its columns stay NULL, never guessed.
    no_x6 = by_key[("06018364000185", AUG31, "Subclasse Subordinada Subordinada 1 |")]
    assert no_x6["pr_desemp_esperado"] is None and no_x6["pr_desemp_real"] is None
    assert no_x6["vl_rentab_mes"] == 0.0


def test_fidc_tranche_flows_x4():
    rows = _fidc("X_4")
    assert len(rows) == 24
    assert _unmatched(rows, fidc_tranche_flows.FIELD_MAP) == set()
    n, cap = _ingest(ingest_fidc, ingest_fidc.ingest_fidc_tranche_flows, rows)
    assert n == 24
    opers = ("Captações no Mês", "Resgates no Mês", "Resgates Solicitados", "Amortizações")
    assert set(_keys(cap["cvm_fidc_tranche_flows"], fidc_tranche_flows.CONFLICT)) == {
        (*k, op) for k in TRANCHE_KEYS for op in opers
    }


# ------------------------------------------------------------------- FIP
def test_fip_quadrimestral():
    rows = _fetch("fip", "inf_quadrimestral", 2025, None,
                  [FX / "cvm_fip/inf_quadrimestral_fip_2025.csv"], zipped=False)
    assert len(rows) == 10
    assert _unmatched(rows, fip_periodic.FIELD_MAP) == set()
    n, cap = _ingest(ingest_misc, ingest_misc.ingest_fip_periodic, rows, "inf_quadrimestral", 2025)
    recs = cap["cvm_fip_periodic"]
    assert n == 10
    q = "inf_quadrimestral"
    aug, dec = date(2025, 8, 31), date(2025, 12, 31)
    key_wo_hash = [c for c in fip_periodic.CONFLICT if c != "row_hash"]
    assert sorted(_keys(recs, key_wo_hash), key=repr) == sorted([
        ("06033235000166", q, aug, "1"),
        ("06033235000166", q, dec, "1"),
        # CVM filed this (fund, date, class) twice with different figures; the
        # row_hash tiebreaker keeps both.
        ("06962594000106", q, aug, "1"),
        ("06962594000106", q, aug, "1"),
        ("06962594000106", q, dec, "1"),
        ("07319087000103", q, aug, "B"),
        ("07319087000103", q, aug, "Classe B"),
        ("07319087000103", q, dec, "1"),
        ("07319087000103", q, dec, "2"),
        ("07319087000103", q, dec, "3"),
    ], key=repr)
    assert len(set(_keys(recs, fip_periodic.CONFLICT))) == 10
    assert {r["period_year"] for r in recs} == {2025}


# --------------------------------------------------------- FII anual, dfin
def test_fii_anual_geral():
    rows = _fetch("fii", "anual", 2025, None, [FX / "cvm_fii_periodic/inf_anual_fii_geral_2025.csv"])
    assert len(rows) == 8
    assert _unmatched(rows, fii_periodic.FIELD_MAP) == set()
    n, cap = _ingest(ingest_fii, ingest_fii.ingest_fii_periodic, rows, "anual", 2025)
    assert n == 8
    assert _keys(cap["cvm_fii_periodic"], fii_periodic.CONFLICT) == [
        (c, "anual", 2025, date(2025, 12, 1), 1)
        for c in (
            "00332266000131", "00613094000174", "00762723000128", "00868235000108",
            "01201140000190", "01235622000161", "01497954000114", "01601918000159",
        )
    ]


def test_fii_dfin():
    rows = _fetch("fii", "dfin", 2025, None, [FX / "cvm_fii_periodic/dfin_fii_2025.csv"], zipped=False)
    assert len(rows) == 10
    assert _unmatched(rows, fii_periodic.FIELD_MAP) == set()
    n, cap = _ingest(ingest_fii, ingest_fii.ingest_fii_periodic, rows, "dfin", 2025)
    assert n == 10
    dec = date(2025, 12, 31)
    assert _keys(cap["cvm_fii_periodic"], fii_periodic.CONFLICT) == [
        ("00332266000131", "dfin", 2025, date(2025, 7, 31), 1),
        *(
            (c, "dfin", 2025, dec, 1)
            for c in (
                "00332266000131", "00613094000174", "00762723000128", "00868235000108",
                "01201140000190", "01235622000161", "01356517000180", "01497954000114",
                "01601918000159",
            )
        ),
    ]


# -------------------------------------------------------------------- CIA
def test_cia_cad_merges_the_two_market_rows():
    rows = _fetch("cia_aberta", "cad", None, None, [FX / "cvm_cia/cad_cia_aberta.csv"], zipped=False)
    assert len(rows) == 12
    assert _unmatched(rows, cia_company.FIELD_MAP) == set()
    n, cap = _ingest(ingest_cia, ingest_cia.ingest_cia_company, rows)
    recs = cap["cia_company"]
    assert n == 11
    assert [(r["cd_cvm"], r["tp_merc"]) for r in recs] == [
        ("25224", None), ("21954", None), ("16330", None), ("16284", ["BOLSA"]),
        ("16349", None), ("35", None), ("16802", None), ("13307", None),
        ("16934", None), ("13005", None),
        ("25283", ["BALCÃO ORGANIZADO", "BOLSA"]),
    ]


def test_cia_ipe_events():
    rows = _fetch("cia_aberta", "ipe", 2026, None, [FX / "cvm_cia/ipe_cia_aberta_2026.csv"])
    assert len(rows) == 10
    assert _unmatched(rows, cia_event.FIELD_MAP) == set()
    n, cap = _ingest(ingest_cia, ingest_cia.ingest_cia_event, rows)
    assert n == 10
    assert _keys(cap["cia_event"], cia_event.CONFLICT) == [
        ("027030IPE290120260106790786-74", 1),
        ("027030IPE281120250125152866-63", 1),
        ("027030IPE260620260125210458-41", 1),
        ("900003IPE011020260121001601-36", 1),
        ("027030IPE270420260182423517-51", 1),
        ("900003IPE061020260154134538-49", 1),
        ("027030IPE311220250139359609-89", 1),
        ("027030IPE311220250200262265-47", 2),
        ("900003IPE311220250127133634-75", 1),
        ("027030IPE310320260112143064-26", 1),
    ]


def test_cia_fca_ticker_map():
    rows = _fetch("cia_aberta", "fca_valor_mobiliario", 2026, None,
                  [FX / "cvm_cia/fca_cia_aberta_valor_mobiliario_2026.csv"])
    assert len(rows) == 10
    assert _unmatched(rows, cia_fca_valor_mobiliario.FIELD_MAP) == set()
    n, cap = _ingest(ingest_cia, ingest_cia.ingest_cia_ticker, rows)
    assert n == 10
    ref = date(2026, 1, 1)
    on, pn = "Ações Ordinárias", "Ações Preferenciais"
    assert _keys(cap["cia_ticker"], cia_fca_valor_mobiliario.CONFLICT) == [
        ("00000000000191", ref, 3, on, "BBAS3", "Bolsa", None, date(2006, 5, 31), date(1977, 7, 20)),
        ("00000208000100", ref, 1, on, "BSLI3", "Bolsa", None, date(2010, 1, 1), date(1993, 9, 24)),
        ("00000208000100", ref, 1, pn, "BSLI4", "Bolsa", None, date(2010, 1, 1), date(1993, 9, 24)),
        ("00001180000126", ref, 4, on, "AXIA3", "Bolsa", None, date(1971, 9, 7), date(1971, 9, 7)),
        # A debenture has no ticker: codneg stays NULL and the row is kept.
        ("00001180000126", ref, 4, "Debêntures", None, "Balcão Organizado", None,
         date(2024, 10, 17), date(2024, 9, 15)),
        ("00001180000126", ref, 4, pn, "AXIA7", "Bolsa", "PNC", date(2025, 12, 22), date(2025, 12, 22)),
        ("00070698000111", ref, 2, on, "CEBR3", "Bolsa", None, date(1994, 7, 4), date(1994, 7, 4)),
        ("00070698000111", ref, 2, pn, "CEBR6", "Bolsa", "PNB", date(1994, 7, 4), date(1994, 7, 4)),
        ("00070698000111", ref, 2, pn, "CEBR5", "Bolsa", "PNA", date(1994, 7, 4), date(1994, 7, 4)),
        ("00080671000100", ref, 2, on, None, None, None, None, None),
    ]


def test_cia_itr_summary_and_statements():
    names = ("itr_cia_aberta_2026.csv", "itr_cia_aberta_DRE_con_2026.csv", "itr_cia_aberta_BPA_con_2026.csv")
    body = _payload([FX / "cvm_cia" / n for n in names], zipped=True)
    with patch.object(CVMFetcher, "_download", AsyncMock(return_value=body)):
        members = CIAFetcher().fetch_zip_members("itr", 2026, include_summary=True)
    assert [(m.member_name, m.grupo, m.escopo, len(m.rows)) for m in members] == [
        ("itr_cia_aberta_2026.csv", "_summary", None, 6),
        ("itr_cia_aberta_BPA_con_2026.csv", "BPA", "con", 12),
        ("itr_cia_aberta_DRE_con_2026.csv", "DRE", "con", 12),
    ]

    summary = members[0]
    assert _unmatched(summary.rows, cia_filing.FIELD_MAP) == set()
    n, cap = _ingest(ingest_cia, ingest_cia.ingest_cia_filing, summary.rows, "itr")
    assert n == 6
    q1, q2 = date(2026, 3, 31), date(2026, 6, 30)
    assert _keys(cap["cia_filing"], cia_filing.CONFLICT) == [
        (cd, "itr", d, 1) for cd in ("1023", "2437", "14451") for d in (q1, q2)
    ]

    accounts = [m for m in members if m.is_account_data]
    # BPA is a balance sheet (a point in time) and has no DT_INI_EXERC; neither
    # statement publishes COLUNA_DF (that is DMPL's).
    assert _unmatched(accounts[0].rows, cia_account.FIELD_MAP) == {"coluna_df", "dt_ini_exerc"}
    assert _unmatched(accounts[1].rows, cia_account.FIELD_MAP) == {"coluna_df"}
    n, cap = _ingest(ingest_cia, ingest_cia.ingest_cia_account, accounts, "itr")
    recs = cap["cia_account"]
    assert n == 24
    keys = _keys(recs, cia_account.CONFLICT)
    assert len(set(keys)) == 24
    pen, ult = "PENÚLTIMO", "ÚLTIMO"
    assert set(keys) == {
        *(("1023", "itr", "BPA", "con", q1, o, None, None, c, 1)
          for c in ("1", "1.01", "1.01.01", "1.01.02", "1.02", "1.02.01") for o in (pen, ult)),
        *(("1023", "itr", "DRE", "con", q1, o, None, ini, c, 1)
          for c in ("3.01", "3.01.01", "3.02", "3.02.01", "3.03", "3.04")
          for o, ini in ((pen, date(2025, 1, 1)), (ult, date(2026, 1, 1)))),
    }
    # VL_CONTA is published in thousands (ESCALA_MOEDA MIL) and stored in reais.
    total_assets = next(r for r in recs if r["grupo"] == "BPA" and r["cd_conta"] == "1" and r["ordem_exerc"] == ult)
    assert total_assets["escala_moeda"] == "MIL"
    assert total_assets["vl_conta"] == 2610200817000.0
