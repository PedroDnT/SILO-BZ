"""FIDC tab_X_7 — guarantees on the credit rights, as filed (migration 45).

The CSVs in tests/fixtures/fidc_tab_x7/ are cut verbatim (latin-1, CRLF, the
real header) from the published files: inf_mensal_fidc_202608.zip, 202607 and
202509 (monthly era), and the 2024, 2022 and 2019 HIST archives. Each one is
put back into a ZIP under its real member name, beside the sibling members it
must not be confused with, and read through CVMFetcher's own member selection
and CSV parser, so the test covers config -> ZIP member -> parse -> validate ->
upsert with nothing hand-typed in between.
"""

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from src.fetchers.cvm_config import DatasetConfig
from src.fetchers.cvm_fetcher import CVMFetcher
from src.parsers.field_maps import fidc_garantia as _garantia
from src.parsers.mapping import FieldMapMismatch
from src.pipeline.ingest_fidc import garantia_row_error, ingest_fidc_garantia

FIXTURES = Path(__file__).parent / "fixtures" / "fidc_tab_x7"

# Members that share the tab_X prefix: the pattern must pick tab_X_7 alone.
_SIBLINGS = ("tab_X", "tab_X_1", "tab_X_1_1", "tab_X_2", "tab_X_6")


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


def _rows(year: int, month: int):
    """The fixture, zipped under its real name and parsed the way fetch() does."""
    doc_type = "hist_mensal_tab_x7" if year <= 2024 else "mensal_tab_x7"
    cfg = DatasetConfig.get_dataset_config("fidc", doc_type)
    member = cfg["csv_name_pattern"].format(year=year, month=month)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, (FIXTURES / member).read_bytes())
        for sib in _SIBLINGS:
            zf.writestr(f"inf_mensal_fidc_{sib}_{year}{month:02d}.csv", b"X;Y\r\n1;2\r\n")
    fetcher = CVMFetcher()
    text = fetcher._extract_csv_from_zip(buf.getvalue(), cfg["csv_name_pattern"], year, month)
    return fetcher._parse_csv(text)


# ---------------------------------------------------------------------------
# parse and key
# ---------------------------------------------------------------------------

def test_monthly_era_rows_are_stored_as_filed(captured):
    n = ingest_fidc_garantia(None, _rows(2026, 8))

    assert n == 3
    assert captured["table"] == "cvm_fidc_garantia"
    assert captured["conflict"] == "cnpj,period"
    by_cnpj = {r["cnpj"]: r for r in captured["rows"]}
    assert by_cnpj["05754060000113"]["vl_garantia"] == 0.0
    assert by_cnpj["05754060000113"]["pr_garantia"] == 0.0
    # PR above 100 is a real filing (the 2026-08 maximum) and is kept.
    mit = by_cnpj["13733804000141"]
    assert mit["period"] == date(2026, 8, 31)
    assert mit["vl_garantia"] == 552320100.42
    assert mit["pr_garantia"] == 113.42
    assert by_cnpj["28819553000190"]["pr_garantia"] == 100.0
    # only the unmodeled columns survive in raw, with the accents decoded
    assert set(mit["raw"]) == {"TP_FUNDO_CLASSE", "DENOM_SOCIAL"}
    assert by_cnpj["28819553000190"]["raw"]["DENOM_SOCIAL"].startswith("PÁTRIA CRÉDITO")


def test_first_published_month_uses_the_cnpj_fundo_header(captured):
    # 2019-11..2020-10 ship CNPJ_FUNDO and no TP_FUNDO_CLASSE.
    rows = _rows(2019, 11)
    assert "CNPJ_FUNDO" in rows[0] and "CNPJ_FUNDO_CLASSE" not in rows[0]

    n = ingest_fidc_garantia(None, rows)

    assert n == 2
    pcg = next(r for r in captured["rows"] if r["cnpj"] == "07727002000126")
    assert pcg == {
        "cnpj": "07727002000126", "period": date(2019, 11, 30),
        "vl_garantia": 450108929.97, "pr_garantia": 100.0,
        "raw": {"DENOM_SOCIAL": "FIDC PCG - BRASIL MULTICARTEIRA"},
    }


def test_fundo_and_classe_lines_of_one_cnpj_are_one_key(captured):
    # HIST 2024-12: SIFRA STAR files a 'Classe' and a 'Fundo' line, same
    # values. (cnpj, period) is the key; both rows reach upsert_rows, which
    # collapses them (last write wins) — nothing differs to lose.
    rows = _rows(2024, 12)
    assert [r["TP_FUNDO_CLASSE"] for r in rows] == ["Classe", "Fundo"]

    ingest_fidc_garantia(None, rows)

    keys = {(r["cnpj"], r["period"]) for r in captured["rows"]}
    assert keys == {("14166140000149", date(2024, 12, 31))}
    assert {(r["vl_garantia"], r["pr_garantia"]) for r in captured["rows"]} == {(0.0, 0.0)}


def test_byte_identical_repeat_is_one_row_in_the_real_upsert(monkeypatch):
    # 2025-09: OPENCO's line appears twice, byte for byte. Run the REAL
    # upsert_rows (its dedup and SQL building); only psycopg2's execute_values
    # is replaced, so the test sees exactly the statement and values it sends.
    import psycopg2.extras

    sent = []
    monkeypatch.setattr(
        psycopg2.extras, "execute_values",
        lambda cur, sql, values, page_size=None: sent.append((sql, values)),
    )

    class _Client:
        def cursor(self):
            class _Cur:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False
            return _Cur()

    rows = _rows(2025, 9)
    assert len(rows) == 2 and rows[0] == rows[1]

    n = ingest_fidc_garantia(_Client(), rows)

    assert n == 1
    ((sql, values),) = sent
    assert sql.startswith("INSERT INTO cvm_fidc_garantia (")
    assert "ON CONFLICT (cnpj,period) DO UPDATE" in sql
    assert len(values) == 1


# ---------------------------------------------------------------------------
# validation: drop and count, never coerce
# ---------------------------------------------------------------------------

def test_negative_value_row_is_dropped_and_counted(captured, caplog):
    # 2026-07: 63.358.336/0001-40 files VL = -0.22.
    rows = _rows(2026, 7)
    assert garantia_row_error(rows[0]) == "vl_garantia: negative (-0.22)"

    with caplog.at_level("INFO", logger="src.pipeline.ingest_fidc"):
        n = ingest_fidc_garantia(None, rows)

    assert n == 0
    assert "rows" not in captured
    assert "1 row(s) dropped by validation {'vl_garantia': 1}" in caplog.text


def test_negative_percentage_is_dropped_too(captured):
    # 2021-10: 38.267.656/0001-48 files PR = -0.01 beside VL = 0.26.
    row = {
        "TP_FUNDO_CLASSE": "Fundo", "CNPJ_FUNDO_CLASSE": "38.267.656/0001-48",
        "DENOM_SOCIAL": "SOMA IV FUNDO DE INVESTIMENTO EM DIREITOS CREDITÓRIOS",
        "DT_COMPTC": "2021-10-31",
        "TAB_X_VL_GARANTIA_DIRCRED": "0.26", "TAB_X_PR_GARANTIA_DIRCRED": "-0.01",
    }
    assert garantia_row_error(row) == "pr_garantia: negative (-0.01)"
    assert ingest_fidc_garantia(None, [row]) == 0


def test_blank_values_are_null_not_zero(captured):
    # 2022-01: RIZA MEYENII leaves both values blank. The row is kept (the fund
    # filed the tab) and both columns are NULL — never a guessed 0.
    n = ingest_fidc_garantia(None, _rows(2022, 1))
    assert n == 1
    (r,) = captured["rows"]
    assert r["cnpj"] == "37087653000160"
    assert r["vl_garantia"] is None
    assert r["pr_garantia"] is None


@pytest.mark.parametrize("field, value, reason", [
    ("CNPJ_FUNDO_CLASSE", "5.754.060/0001-13", "cnpj"),   # 13 digits: not zero-padded into a guess
    ("CNPJ_FUNDO_CLASSE", "05.754.060/0001-14", "cnpj"),  # check digits do not verify
    ("CNPJ_FUNDO_CLASSE", "", "cnpj"),
    ("DT_COMPTC", "2026-02-30", "period"),
    ("DT_COMPTC", "", "period"),
    ("TAB_X_VL_GARANTIA_DIRCRED", "abc", "vl_garantia"),   # coerce() would make it NULL
    ("TAB_X_PR_GARANTIA_DIRCRED", "1O0.00", "pr_garantia"),
])
def test_invalid_rows_are_dropped_not_coerced(captured, field, value, reason):
    good = _rows(2026, 8)[1]
    bad = dict(good, **{field: value})
    assert garantia_row_error(good) is None
    assert garantia_row_error(bad).startswith(reason + ":")

    n = ingest_fidc_garantia(None, [good, bad])

    assert n == 1
    assert captured["rows"][0]["cnpj"] == "13733804000141"


def test_header_drift_raises():
    rows = _rows(2026, 8)
    for r in rows:
        r["TAB_X_VL_GARANTIA"] = r.pop("TAB_X_VL_GARANTIA_DIRCRED")
    with pytest.raises(FieldMapMismatch):
        ingest_fidc_garantia(None, rows)


def test_map_names_exactly_the_published_columns():
    header = (FIXTURES / "inf_mensal_fidc_tab_X_7_202608.csv").read_bytes().decode("latin-1").splitlines()[0]
    published = set(header.split(";"))
    modeled = {c for cands, _ in _garantia.FIELD_MAP.values() for c in cands}
    # every value column CVM publishes is modeled; the rest stays in raw
    assert published - modeled == {"TP_FUNDO_CLASSE", "DENOM_SOCIAL"}
    assert _garantia.CONFLICT == ("cnpj", "period")


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------

def test_tab_x7_is_backfilled_only_from_2019_11():
    from src.pipeline.cvm_pipeline import (
        _FIDC_TAB_FIRST_PERIOD, _fidc_tab_doc_type, _iter_month_pairs,
    )

    assert _FIDC_TAB_FIRST_PERIOD["x7"] == date(2019, 11, 1)
    months = _iter_month_pairs(list(range(2013, 2027)), date(2026, 9, 24),
                               available_from=_FIDC_TAB_FIRST_PERIOD["x7"])
    assert months[0] == (2019, 11)
    assert (2019, 10) not in months
    assert _fidc_tab_doc_type("x7", 2024) == "hist_mensal_tab_x7"
    assert _fidc_tab_doc_type("x7", 2025) == "mensal_tab_x7"


def test_both_eras_have_a_config_that_names_tab_x_7():
    for doc_type, archive in (("hist_mensal_tab_x7", "/HIST/inf_mensal_fidc_{year}.zip"),
                              ("mensal_tab_x7", "/inf_mensal_fidc_{year}{month:02d}.zip")):
        cfg = DatasetConfig.get_dataset_config("fidc", doc_type)
        assert cfg["csv_name_pattern"] == "inf_mensal_fidc_tab_X_7_{year}{month:02d}.csv"
        assert cfg["url_pattern"].endswith(archive)


@pytest.mark.asyncio
async def test_ingestor_method_logs_under_mensal_tab_x7_and_picks_the_archive(monkeypatch):
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = None
    calls = {}
    ing._log_start = lambda run_id, entity, doc_type, y, m: calls.setdefault("log", (entity, doc_type, y, m))
    ing._log_finish = lambda run_id, n, error=None, fetched=None: calls.setdefault("finish", (n, error, fetched))

    async def fake_fetch(entity, doc_type, year, month):
        calls["fetch"] = (entity, doc_type, year, month)
        return _rows(year, month)

    ing._fetch_all_pages = fake_fetch
    monkeypatch.setattr("src.pipeline.ingest_fidc.upsert_rows",
                        lambda conn, table, rows, conflict_columns=None: len(rows))

    n = await ing.ingest_fidc_garantia(2024, 12)

    assert calls["log"] == ("fidc", "mensal_tab_x7", 2024, 12)
    assert calls["fetch"] == ("fidc", "hist_mensal_tab_x7", 2024, 12)
    assert n == 2  # both source lines handed on; upsert_rows collapses the pair
    assert calls["finish"] == (2, None, 2)


@pytest.mark.asyncio
async def test_daily_update_schedules_garantia_in_the_fidc_window(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from src.pipeline.cvm_pipeline import CVMIngestor

    monkeypatch.setenv("CVM_DAILY_SCOPE", "fidc")
    ing = CVMIngestor.__new__(CVMIngestor)
    for name in (
        "ingest_fund_registry", "ingest_fund_registry_cvm175", "ingest_etf_registry",
        "ingest_fidc_mensal", "ingest_fidc_tranche", "ingest_fidc_tranche_flows",
        "ingest_fidc_aging", "ingest_fidc_setor", "ingest_fidc_scr",
        "ingest_fidc_sacado", "ingest_fidc_cedente", "ingest_fidc_garantia",
    ):
        setattr(ing, name, AsyncMock(return_value=1))
    ing._refresh_etf_metrics = MagicMock()
    seen = []
    ing._monthly_targets = lambda entity, doc_type, today: seen.append((entity, doc_type)) or [(2026, 8)]

    totals = await ing.daily_update()

    assert ("fidc", "mensal_tab_x7") in seen
    ing.ingest_fidc_garantia.assert_awaited_with(2026, 8)
    assert totals["cvm_fidc_garantia"] == 1
