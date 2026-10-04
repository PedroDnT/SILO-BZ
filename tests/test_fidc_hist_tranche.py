"""FIDC tranche, flows, aging and delinquency from the HIST archives (issue #556).

The header lines below are the ones probe_cvm_headers.yml printed for CVM's
FIDC informe mensal (runs 37217592901 and 37218127539, 2026-10-04): every HIST
archive 2013-2024 carries tabs VI, X_2, X_3, X_4 and X_6 for twelve months,
with the same value columns as the monthly era. Only the fund id changes:
CNPJ_FUNDO until 2020-10 in tab VI and until 2023-09 in X_2..X_6, then
TP_FUNDO_CLASSE + CNPJ_FUNDO_CLASSE. The data lines are made up for the test;
the headers are copied from the probe log.

Each CSV is zipped under its real member name beside the sibling members it
must not be confused with, and read through CVMFetcher's own member selection
and CSV parser, so config -> ZIP member -> parse -> map -> upsert is covered.
"""

import io
import zipfile
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.fetchers.cvm_fetcher import CVMFetcher
from src.pipeline.ingest_fidc import (
    inadimpl_by_key,
    ingest_fidc_aging,
    ingest_fidc_tranche,
    ingest_fidc_tranche_flows,
)

_OLD_ID = "CNPJ_FUNDO;DENOM_SOCIAL;DT_COMPTC"
_NEW_ID = "TP_FUNDO_CLASSE;CNPJ_FUNDO_CLASSE;DENOM_SOCIAL;DT_COMPTC"

_VI_VALUES = (
    "TAB_VI_A_VL_DIRCRED_PRAZO;TAB_VI_A1_VL_PRAZO_VENC_30;TAB_VI_A2_VL_PRAZO_VENC_60;"
    "TAB_VI_A3_VL_PRAZO_VENC_90;TAB_VI_A4_VL_PRAZO_VENC_120;TAB_VI_A5_VL_PRAZO_VENC_150;"
    "TAB_VI_A6_VL_PRAZO_VENC_180;TAB_VI_A7_VL_PRAZO_VENC_360;TAB_VI_A8_VL_PRAZO_VENC_720;"
    "TAB_VI_A9_VL_PRAZO_VENC_1080;TAB_VI_A10_VL_PRAZO_VENC_MAIOR_1080;TAB_VI_B_VL_DIRCRED_INAD;"
    "TAB_VI_B1_VL_INAD_30;TAB_VI_B2_VL_INAD_60;TAB_VI_B3_VL_INAD_90;TAB_VI_B4_VL_INAD_120;"
    "TAB_VI_B5_VL_INAD_150;TAB_VI_B6_VL_INAD_180;TAB_VI_B7_VL_INAD_360;TAB_VI_B8_VL_INAD_720;"
    "TAB_VI_B9_VL_INAD_1080;TAB_VI_B10_VL_INAD_MAIOR_1080;TAB_VI_C_VL_DIRCRED_ANTECIPADO;"
    "TAB_VI_C1_VL_ANTECIPADO_30;TAB_VI_C2_VL_ANTECIPADO_60;TAB_VI_C3_VL_ANTECIPADO_90;"
    "TAB_VI_C4_VL_ANTECIPADO_120;TAB_VI_C5_VL_ANTECIPADO_150;TAB_VI_C6_VL_ANTECIPADO_180;"
    "TAB_VI_C7_VL_ANTECIPADO_360;TAB_VI_C8_VL_ANTECIPADO_720;TAB_VI_C9_VL_ANTECIPADO_1080;"
    "TAB_VI_C10_VL_ANTECIPADO_MAIOR_1080"
)
_VALUES = {
    "VI": _VI_VALUES,
    "X_2": "TAB_X_CLASSE_SERIE;TAB_X_QT_COTA;TAB_X_VL_COTA",
    "X_3": "TAB_X_CLASSE_SERIE;TAB_X_VL_RENTAB_MES",
    "X_4": "TAB_X_TP_OPER;TAB_X_CLASSE_SERIE;TAB_X_VL_TOTAL;TAB_X_QT_COTA",
    "X_6": "TAB_X_CLASSE_SERIE;TAB_X_PR_DESEMP_ESPERADO;TAB_X_PR_DESEMP_REAL",
}
# Column counts the probe reported per generation.
_COLS = {
    ("VI", "old"): 36, ("VI", "new"): 37,
    ("X_2", "old"): 6, ("X_2", "new"): 7,
    ("X_3", "old"): 5, ("X_3", "new"): 6,
    ("X_4", "old"): 7, ("X_4", "new"): 8,
    ("X_6", "old"): 6, ("X_6", "new"): 7,
}
_SIBLINGS = {
    "VI": ("V", "VII", "VIII"),
    "X_2": ("X", "X_1", "X_1_1", "X_3", "X_7"),
    "X_3": ("X", "X_2", "X_4"),
    "X_4": ("X", "X_3", "X_5"),
    "X_6": ("X", "X_5", "X_7"),
}

CNPJ = "11.003.181/0001-26"
CNPJ_DIGITS = "11003181000126"


def _header(tab: str, gen: str) -> str:
    header = f"{_OLD_ID if gen == 'old' else _NEW_ID};{_VALUES[tab]}"
    assert len(header.split(";")) == _COLS[(tab, gen)]
    return header


def _line(gen: str, period: str, values: list) -> str:
    ident = [CNPJ, "FIDC TESTE", period] if gen == "old" else ["Classe", CNPJ, "FIDC TESTE", period]
    return ";".join(ident + [str(v) for v in values])


def _rows(tab: str, gen: str, year: int, month: int, value_lines: list) -> list:
    """Zip the CSV under its member name with siblings; parse it as fetch() does."""
    period = f"{year}-{month:02d}-01"
    text = "\r\n".join([_header(tab, gen)] + [_line(gen, period, v) for v in value_lines]) + "\r\n"
    doc_type = ("hist_mensal_tab_" if year <= 2024 else "mensal_tab_") + tab.replace("_", "").lower()
    cfg = DatasetConfig.get_dataset_config("fidc", doc_type)
    member = cfg["csv_name_pattern"].format(year=year, month=month)
    assert member == f"inf_mensal_fidc_tab_{tab}_{year}{month:02d}.csv"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, text.encode("latin-1"))
        for sib in _SIBLINGS[tab]:
            zf.writestr(f"inf_mensal_fidc_tab_{sib}_{year}{month:02d}.csv", b"X;Y\r\n1;2\r\n")
    fetcher = CVMFetcher()
    raw = fetcher._extract_csv_from_zip(buf.getvalue(), cfg["csv_name_pattern"], year, month)
    return fetcher._parse_csv(raw)


def _vi_values(inad_total="500.00", buckets=("100.00",) * 10):
    a = ["1000.00"] + ["90.00"] * 10
    c = ["0.00"] * 11
    return a + [inad_total] + list(buckets) + c


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_upsert(conn, table, rows, conflict_columns=None, **kw):
        seen.setdefault(table, []).extend(rows)
        return len(rows)

    monkeypatch.setattr("src.pipeline.ingest_fidc.upsert_rows", fake_upsert)
    return seen


# Both id generations, in the HIST era where each one was filed.
GENS = [("old", 2013, 1), ("new", 2024, 6)]


# ---------------------------------------------------------------------------
# configs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tab", ["VI", "X_2", "X_3", "X_4", "X_6"])
def test_hist_config_points_at_the_yearly_archive(tab):
    key = "hist_mensal_tab_" + tab.replace("_", "").lower()
    cfg = DatasetConfig.get_dataset_config("fidc", key)
    assert cfg["url_pattern"].endswith("/HIST/inf_mensal_fidc_{year}.zip")
    assert cfg["csv_name_pattern"] == f"inf_mensal_fidc_tab_{tab}_{{year}}{{month:02d}}.csv"


# ---------------------------------------------------------------------------
# parse, both header generations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gen,year,month", GENS)
def test_tranche_joins_x2_x3_x6(captured, gen, year, month):
    x2 = _rows("X_2", gen, year, month, [["SENIOR 1", "1000.5", "1.234567"]])
    x3 = _rows("X_3", gen, year, month, [["SENIOR 1", "0.98"]])
    x6 = _rows("X_6", gen, year, month, [["SENIOR 1", "1.10", "0.98"]])

    assert ingest_fidc_tranche(None, x2, x3, x6, year, month) == 1
    (r,) = captured["cvm_fidc_tranche"]
    assert r["cnpj"] == CNPJ_DIGITS
    assert str(r["period"]) == f"{year}-{month:02d}-01"
    assert r["classe_serie"] == "SENIOR 1"
    assert float(r["qt_cota"]) == 1000.5
    assert float(r["vl_cota"]) == 1.234567
    assert float(r["vl_rentab_mes"]) == 0.98
    assert float(r["pr_desemp_esperado"]) == 1.10
    assert float(r["pr_desemp_real"]) == 0.98


@pytest.mark.parametrize("gen,year,month", GENS)
def test_flows_from_x4(captured, gen, year, month):
    x4 = _rows("X_4", gen, year, month, [
        ["Captacao", "SENIOR 1", "500000.00", "400"],
        ["Resgate", "SENIOR 1", "", ""],
    ])

    assert ingest_fidc_tranche_flows(None, x4) == 2
    cap, res = captured["cvm_fidc_tranche_flows"]
    assert cap["cnpj"] == CNPJ_DIGITS and cap["tp_oper"] == "Captacao"
    assert float(cap["vl_total"]) == 500000.0
    assert float(cap["qt_cota"]) == 400
    assert res["vl_total"] is None and res["qt_cota"] is None  # blank stays NULL


@pytest.mark.parametrize("gen,year,month", GENS)
def test_aging_from_vi(captured, gen, year, month):
    vi = _rows("VI", gen, year, month, [_vi_values()])

    assert ingest_fidc_aging(None, vi) == 1
    (r,) = captured["cvm_fidc_aging"]
    assert r["cnpj"] == CNPJ_DIGITS
    assert float(r["vl_prazo_30"]) == 90.0
    assert float(r["vl_inad_maior_1080"]) == 100.0
    assert float(r["vl_total_inad"]) == 500.0


@pytest.mark.parametrize("gen,year,month", GENS)
def test_inadimpl_is_the_filed_total_not_the_bucket_sum(gen, year, month):
    # Buckets sum to 1000, the filed total says 500: the filed figure wins.
    vi = _rows("VI", gen, year, month, [_vi_values("500.00", ("100.00",) * 10)])
    out = inadimpl_by_key(vi)
    assert [float(v) for v in out.values()] == [500.0]


def test_blank_inadimpl_total_is_absent_not_zero():
    vi = _rows("VI", "old", 2013, 1, [_vi_values("", ("100.00",) * 10)])
    assert inadimpl_by_key(vi) == {}


# ---------------------------------------------------------------------------
# HIST mensal: vl_inadimpl read from tab VI
# ---------------------------------------------------------------------------

_II_OLD = "CNPJ_FUNDO;DENOM_SOCIAL;DT_COMPTC;TAB_II_VL_CARTEIRA"
_III_OLD = "CNPJ_FUNDO;DENOM_SOCIAL;DT_COMPTC;TAB_III_VL_PASSIVO"


def _csv_rows(header: str, line: str) -> list:
    return CVMFetcher()._parse_csv(f"{header}\r\n{line}\r\n")


def _hist_ingestor(monkeypatch, pages):
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = None
    ing._log_start = MagicMock()
    ing._log_finish = MagicMock()

    async def fake_fetch(entity, doc_type, year, month):
        value = pages(doc_type, year, month)
        if isinstance(value, Exception):
            raise value
        return value

    ing._fetch_all_pages = fake_fetch
    stored = []
    monkeypatch.setattr(
        "src.pipeline.cvm_pipeline.upsert_rows",
        lambda conn, table, rows, conflict_columns=None: stored.extend(rows) or len(rows),
    )
    monkeypatch.setattr("src.pipeline.cvm_pipeline.seed_fund_registry_from_hist", lambda c, r: 0)
    return ing, stored


@pytest.mark.asyncio
async def test_hist_mensal_reads_vl_inadimpl_from_tab_vi(monkeypatch):
    # 2020-11: tab_II still keys on CNPJ_FUNDO in this fixture while tab_VI
    # already uses CNPJ_FUNDO_CLASSE, so the join must match on the coerced CNPJ.
    def pages(doc_type, year, month):
        period = f"{year}-{month:02d}-01"
        if doc_type == "hist_mensal_tab_ii":
            return _csv_rows(_II_OLD, f"{CNPJ};FIDC TESTE;{period};2000.00")
        if doc_type == "hist_mensal_tab_iii":
            return _csv_rows(_III_OLD, f"{CNPJ};FIDC TESTE;{period};300.00")
        if doc_type == "hist_mensal_tab_vi":
            return _rows("VI", "new", year, month, [_vi_values("500.00", ("100.00",) * 10)])
        raise AssertionError(doc_type)

    ing, stored = _hist_ingestor(monkeypatch, pages)
    await ing.ingest_fidc_hist_mensal(2020)

    assert len(stored) == 12
    for r in stored:
        assert r["cnpj"] == CNPJ_DIGITS
        assert float(r["vl_inadimpl"]) == 500.0
        assert r["vl_total"] == 2000.0


@pytest.mark.asyncio
async def test_hist_mensal_keeps_pl_when_tab_vi_fails(monkeypatch):
    def pages(doc_type, year, month):
        period = f"{year}-{month:02d}-01"
        if doc_type == "hist_mensal_tab_ii":
            return _csv_rows(_II_OLD, f"{CNPJ};FIDC TESTE;{period};2000.00")
        if doc_type == "hist_mensal_tab_iii":
            return _csv_rows(_III_OLD, f"{CNPJ};FIDC TESTE;{period};300.00")
        return RuntimeError("member not found in archive")

    ing, stored = _hist_ingestor(monkeypatch, pages)
    await ing.ingest_fidc_hist_mensal(2013)

    assert len(stored) == 12
    assert all(r["vl_inadimpl"] is None for r in stored)
    assert all(r["vl_patrim_liq"] == 1700.0 for r in stored)


# ---------------------------------------------------------------------------
# ingestor methods: archive by year, one log series
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("year,prefix", [(2013, "hist_mensal_tab_"), (2024, "hist_mensal_tab_"),
                                         (2025, "mensal_tab_")])
async def test_methods_pick_the_archive_and_log_under_one_doc_type(monkeypatch, year, prefix):
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = None
    logged, fetched = [], []
    ing._log_start = lambda run_id, entity, doc_type, y, m: logged.append(doc_type)
    ing._log_finish = MagicMock()

    async def fake_fetch(entity, doc_type, y, m):
        fetched.append(doc_type)
        return []

    ing._fetch_all_pages = fake_fetch
    await ing.ingest_fidc_tranche(year, 3)
    await ing.ingest_fidc_tranche_flows(year, 3)
    await ing.ingest_fidc_aging(year, 3)

    assert logged == ["mensal_tab_x2", "mensal_tab_x4", "mensal_tab_vi"]
    assert fetched == [prefix + t for t in ("x2", "x3", "x6", "x4", "vi")]


# ---------------------------------------------------------------------------
# backfill planning
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_schedules_tranche_flows_aging_from_2013():
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    for name in (
        "ingest_fidc_hist_mensal", "ingest_fidc_mensal", "ingest_fidc_tranche",
        "ingest_fidc_tranche_flows", "ingest_fidc_aging", "ingest_fidc_setor",
        "ingest_fidc_scr", "ingest_fidc_sacado", "ingest_fidc_cedente",
        "ingest_fidc_garantia",
    ):
        setattr(ing, name, AsyncMock(return_value=1))

    async def run_tasks(tasks, _concurrency, totals, _label):
        for task in tasks:
            totals[task.table] += await task.operation

    ing._run_task_batches = run_tasks

    totals = await ing.backfill(start_year=2012, end_year=2024, entity_filter="fidc")

    expected = [(y, m) for y in range(2013, 2025) for m in range(1, 13)]
    for name, table in (("ingest_fidc_tranche", "cvm_fidc_tranche"),
                        ("ingest_fidc_tranche_flows", "cvm_fidc_tranche_flows"),
                        ("ingest_fidc_aging", "cvm_fidc_aging")):
        method = getattr(ing, name)
        assert [c.args for c in method.await_args_list] == expected
        assert totals[table] == 144
    ing.ingest_fidc_mensal.assert_not_awaited()  # current-era form only from 2025
