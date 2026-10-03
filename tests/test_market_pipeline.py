"""DI1 futures, B3 reference curves, UST, Brent, OFR FSI, gated VIX (migration 48).

Fixtures are trimmed REAL files fetched on 2026-09-26/27:
b3_price_report_20260925_sample.xml (five DI1 contracts and two other
instruments), b3_price_report_20180102_sample.xml (an untraded DI1),
b3_taxaswap_20260925_sample.txt (PRE / DOC / DPL vertices plus three DIC
rows), the Treasury par-curve CSV header of 2008 and 2026, Cboe
VIX_History.csv, an EIA API v2 answer, OFR's fsi.csv and its revision
workbook FSI_Revision_History_2023-06-27.xlsx (first rows of each sheet,
values unchanged). Nothing is fetched here. Contracts:
src/fetchers/b3_pesquisapregao_fetcher.py, src/fetchers/global_market_fetcher.py,
docs/reference/research/dustin_br_data_sources.md.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.fetchers.b3_pesquisapregao_fetcher import (
    B3FileFetchError, B3FileNotPublished, price_report_name, taxa_swap_name,
    unwrap_price_report, unwrap_taxa_swap,
)
from src.parsers import b3_price_report as pr
from src.parsers import b3_taxa_swap as ts
from src.parsers import global_market as gm
from src.pipeline import market_pipeline as mp

FIX = Path(__file__).parent / "fixtures"
PR_2026 = (FIX / "b3_price_report_20260925_sample.xml").read_bytes()
PR_2018 = (FIX / "b3_price_report_20180102_sample.xml").read_bytes()
TS_2026 = (FIX / "b3_taxaswap_20260925_sample.txt").read_text(encoding="latin-1")
# The complete PRE, DOC and DPL curves of the same file (858 vertices).
TS_CURVES = (FIX / "b3_taxaswap_20260925_curves.txt").read_text(encoding="latin-1")
S_2026 = date(2026, 9, 25)


def _zip(members: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


EMPTY_ZIP = _zip({})


# ---------------------------------------------------------------------------
# Price Report (BVBG.086.01)
# ---------------------------------------------------------------------------

def test_price_report_keeps_the_published_di1_fields():
    rows, counts = pr.parse_price_report(PR_2026, session=S_2026, origin="fixture")
    by = {r["ticker"]: r for r in rows}
    assert set(by) == {"DI1F27", "DI1J27", "DI1F29", "DI1F32", "DI1F37"}
    assert counts == {"kept": 5, "dropped_invalid": 0, "dropped_non_outright": 0}
    f27 = by["DI1F27"]
    # As printed in the file: settlement PU and rate, open interest, volume.
    assert f27["settlement_price"] == Decimal("96726.67")
    assert f27["settlement_rate"] == Decimal("13.55")
    assert f27["prev_settlement_rate"] == Decimal("13.561")
    assert f27["open_interest"] == 7869476
    assert f27["contracts"] == 559146
    assert f27["trades"] == 3837
    # DI1 is quoted in rate: the low RATE is the high PU. Stored as published.
    assert (f27["open_px"], f27["low_px"], f27["high_px"], f27["close_px"]) == (
        Decimal("13.575"), Decimal("13.545"), Decimal("13.575"), Decimal("13.55"))
    assert f27["settlement_status"] == "F"
    assert f27["report_created_at"].isoformat() == "2026-09-25T20:31:13"
    assert f27["raw"]["TckrSymb"] == "DI1F27"


def test_an_untraded_contract_keeps_null_prices_never_zero():
    rows, _ = pr.parse_price_report(PR_2018, session=date(2018, 1, 2))
    (row,) = rows
    assert row["ticker"] == "DI1N24"
    assert row["open_interest"] == 9550 and row["settlement_rate"] == Decimal("10.125")
    for col in ("trades", "contracts", "open_px", "low_px", "high_px", "close_px", "avg_px"):
        assert row[col] is None, col


def test_the_settlement_rate_and_pu_agree_on_a_whole_number_of_business_days():
    """PU = 100000 / (1 + r)^(du/252): the published pair implies an integer
    du. A file where it does not would mean a column moved."""
    rows, _ = pr.parse_price_report(PR_2026, session=S_2026)
    for r in rows:
        du = 252 * math.log(100000 / float(r["settlement_price"])) / math.log(1 + float(r["settlement_rate"]) / 100)
        assert abs(du - round(du)) < 0.05, (r["ticker"], du)


def _reports(*tickers: str, dt: str = "2026-09-25", adj: str = "96726.67") -> bytes:
    body = "".join(
        f"<PricRpt><TradDt><Dt>{dt}</Dt></TradDt><SctyId><TckrSymb>{t}</TckrSymb></SctyId>"
        f'<FinInstrmAttrbts><AdjstdQt Ccy="BRL">{adj}</AdjstdQt><AdjstdQtTax Ccy="BRL">13.55</AdjstdQtTax>'
        "</FinInstrmAttrbts></PricRpt>"
        for t in tickers
    )
    return ('<Document xmlns="urn:bvmf.217.01.xsd"><BizGrp><CreDtAndTm>2026-09-25T20:31:13</CreDtAndTm>'
            f"{body}</BizGrp></Document>").encode()


_one_report = _reports


def test_non_outright_tickers_of_the_root_are_dropped_and_counted():
    rows, counts = pr.parse_price_report(_one_report("DI1F27F28"), session=S_2026)
    assert rows == [] and counts["dropped_non_outright"] == 1


def test_an_impossible_pu_is_dropped_not_clipped():
    rows, counts = pr.parse_price_report(_one_report("DI1F27", adj="0"), session=S_2026)
    assert rows == [] and counts["dropped_invalid"] == 1


def test_a_row_dated_another_session_raises():
    with pytest.raises(pr.PriceReportFormatError, match="dated 2026-09-24"):
        pr.parse_price_report(_one_report("DI1F27", dt="2026-09-24"), session=S_2026)


def test_a_ticker_twice_in_one_report_raises():
    with pytest.raises(pr.PriceReportFormatError, match="twice"):
        pr.parse_price_report(_reports("DI1F27", "DI1F27"), session=S_2026)


def test_a_file_without_price_reports_raises():
    with pytest.raises(pr.PriceReportFormatError, match="no PricRpt"):
        pr.parse_price_report(b"<Document/>", session=S_2026)


def test_the_latest_version_is_chosen_by_its_own_timestamp_not_its_name():
    early = PR_2026.replace(b"2026-09-25T20:31:13", b"2026-09-25T18:37:43")
    inner = _zip({"BVBG_z_first.xml": PR_2026, "BVBG_a_second.xml": early})
    name, xml = unwrap_price_report(_zip({"PR260925.zip": inner}), "PR260925.zip")
    assert name == "BVBG_z_first.xml" and xml == PR_2026


def test_a_version_zipped_once_more_is_opened_and_still_ranked_by_timestamp():
    # PR230719.zip: two versions as BVBG...zip members beside one BVBG...xml.
    early = PR_2026.replace(b"2026-09-25T20:31:13", b"2026-09-25T18:37:43")
    nested_early = _zip({"BVBG_early.xml": early})
    inner = _zip({"BVBG_early.zip": nested_early, "BVBG_latest.xml": PR_2026})
    name, xml = unwrap_price_report(_zip({"PR230719.zip": inner}), "PR230719.zip")
    assert name == "BVBG_latest.xml" and xml == PR_2026
    # The latest version may itself be the nested one.
    inner = _zip({"BVBG_latest.zip": _zip({"BVBG_latest.xml": PR_2026}), "BVBG_early.xml": early})
    name, xml = unwrap_price_report(_zip({"PR230719.zip": inner}), "PR230719.zip")
    assert name == "BVBG_latest.xml" and xml == PR_2026
    # A nested zip holding anything but one file is a packaging change, not a guess.
    inner = _zip({"BVBG_two.zip": _zip({"a.xml": PR_2026, "b.xml": early})})
    with pytest.raises(B3FileFetchError, match="expected one XML"):
        unwrap_price_report(_zip({"PR230719.zip": inner}), "PR230719.zip")


def test_an_empty_archive_is_not_published_not_an_error():
    with pytest.raises(B3FileNotPublished):
        unwrap_price_report(EMPTY_ZIP, "PR260927.zip")
    with pytest.raises(B3FileNotPublished):
        unwrap_taxa_swap(EMPTY_ZIP, "TS260927.ex_")
    with pytest.raises(B3FileFetchError, match="not a zip"):
        unwrap_taxa_swap(b"<html>maintenance</html>", "TS260925.ex_")


def test_file_names_follow_b3s_yymmdd_pattern():
    assert price_report_name(date(2018, 1, 2)) == "PR180102.zip"
    assert taxa_swap_name(date(2008, 1, 2)) == "TS080102.ex_"


# ---------------------------------------------------------------------------
# TaxaSwap reference rates
# ---------------------------------------------------------------------------

def _sfx(text: str) -> bytes:
    """The real shape: a zip holding a self-extracting exe (stub + zip)."""
    exe = b"MZ" + b"\x00" * 4000 + _zip({"TaxaSwap.txt": text.encode("latin-1")})
    return _zip({"TS260925.ex_": exe})


def test_taxa_swap_unwraps_the_self_extracting_archive():
    assert unwrap_taxa_swap(_sfx(TS_2026), "TS260925.ex_") == TS_2026


def test_taxa_swap_keeps_only_the_configured_curves():
    rows, counts = ts.parse_taxa_swap(TS_2026, session=S_2026)
    # DPL (clean IPCA coupon) is kept; DIC (the dirty-coupon poll) is in the
    # fixture and skipped.
    assert ts.DEFAULT_CURVES == ("PRE", "DOC", "DPL")
    assert {r["curve"] for r in rows} == {"PRE", "DOC", "DPL"}
    assert "DIC" in {line[21:26].strip() for line in TS_2026.splitlines()}
    assert counts["kept"] == len(rows) and counts["dropped_invalid"] == 0
    first = min((r for r in rows if r["curve"] == "PRE"), key=lambda r: r["calendar_days"])
    assert (first["calendar_days"], first["business_days"], first["rate"], first["vertex_type"]) == (
        3, 1, Decimal("13.65"), "F")


def test_pre_equals_the_di1_settlement_rate_at_each_contract_maturity():
    """The measured property the research layer leans on: B3's PRE curve has a
    moving vertex at every DI1 maturity, at that contract's settlement rate."""
    curve = {r["business_days"]: r for r in ts.parse_taxa_swap(TS_CURVES, session=S_2026)[0] if r["curve"] == "PRE"}
    rows, _ = pr.parse_price_report(PR_2026, session=S_2026)
    checked = 0
    for r in rows:
        du = round(252 * math.log(100000 / float(r["settlement_price"])) / math.log(1 + float(r["settlement_rate"]) / 100))
        assert du in curve, r["ticker"]
        assert curve[du]["rate"] == r["settlement_rate"], r["ticker"]
        assert curve[du]["vertex_type"] == "M"
        checked += 1
    assert checked == 5  # every DI1 contract in the fixture, out to DI1F37


def test_taxa_swap_layout_changes_raise():
    line = TS_2026.splitlines()[0]
    with pytest.raises(ts.TaxaSwapFormatError, match="characters"):
        ts.parse_taxa_swap(line + "X", session=S_2026)
    with pytest.raises(ts.TaxaSwapFormatError, match="dated"):
        ts.parse_taxa_swap(TS_2026, session=date(2026, 9, 24))
    with pytest.raises(ts.TaxaSwapFormatError, match="not in the file"):
        ts.parse_taxa_swap(TS_2026, session=S_2026, curves=("PRE", "XYZ"))
    pre = [l for l in TS_2026.splitlines() if l[21:26].strip() == "PRE"][0]
    with pytest.raises(ts.TaxaSwapFormatError, match="twice"):
        ts.parse_taxa_swap(pre + "\n" + pre, session=S_2026, curves=("PRE",))


def test_an_earlier_file_republished_under_a_later_date_is_stale_not_broken():
    # B3 served the 2010-12-23 file under 2010-12-24; here the 2026-09-25 file
    # under 2026-09-28. Nothing may be stored under the later date.
    with pytest.raises(ts.TaxaSwapStaleFile, match="republished that file under 2026-09-28"):
        ts.parse_taxa_swap(TS_2026, session=date(2026, 9, 28))
    # One earlier-dated line among current ones is a broken file, not a republication.
    lines = TS_2026.splitlines()
    i = next(k for k, line in enumerate(lines) if line[21:26].strip() == "PRE")
    lines[i] = lines[i][:11] + "20260924" + lines[i][19:]
    with pytest.raises(ts.TaxaSwapFormatError, match="dated 2026-09-24") as exc:
        ts.parse_taxa_swap("\n".join(lines), session=S_2026)
    assert not isinstance(exc.value, ts.TaxaSwapStaleFile)


def test_short_doc_vertices_of_hundreds_of_percent_are_kept_as_published():
    line = "0068520010120260914T1DOC  DIxXDOL Cupom l0000100001+00004303000000F00001"
    (row,), counts = ts.parse_taxa_swap(line, session=date(2026, 9, 14), curves=("DOC",))
    assert row["rate"] == Decimal("430.3") and counts["dropped_invalid"] == 0


def test_a_vertex_with_more_business_than_calendar_days_is_dropped():
    good, other = [l for l in TS_2026.splitlines() if l[21:26].strip() == "PRE"][:2]
    bad = other[:41] + "00005" + "00009" + other[51:]
    rows, counts = ts.parse_taxa_swap(good + "\n" + bad, session=S_2026, curves=("PRE",))
    assert len(rows) == 1 and counts["dropped_invalid"] == 1
    with pytest.raises(ts.TaxaSwapFormatError, match="failed validation"):
        ts.parse_taxa_swap(bad, session=S_2026, curves=("PRE",))


# ---------------------------------------------------------------------------
# Treasury, Cboe, EIA
# ---------------------------------------------------------------------------

def test_treasury_2026_columns_including_the_new_tenors():
    rows, counts = gm.parse_treasury_par_csv((FIX / "ust_par_yield_2026_sample.csv").read_text())
    assert counts == {"kept": 42, "dropped_invalid": 0}
    got = {(r["series_id"], r["observation_date"]): r["value"] for r in rows}
    assert got[("UST_PAR_10Y", date(2026, 9, 25))] == Decimal("5.17")
    assert got[("UST_PAR_6W", date(2026, 9, 25))] == Decimal("4.14")
    assert {r["unit"] for r in rows} == {"pct"} and {r["source"] for r in rows} == {"us_treasury"}


def test_treasury_2008_has_no_new_tenors_and_that_is_fine():
    rows, _ = gm.parse_treasury_par_csv((FIX / "ust_par_yield_2008_sample.csv").read_text())
    assert {r["series_id"] for r in rows} == {
        "UST_PAR_1M", "UST_PAR_3M", "UST_PAR_6M", "UST_PAR_1Y", "UST_PAR_2Y", "UST_PAR_3Y",
        "UST_PAR_5Y", "UST_PAR_7Y", "UST_PAR_10Y", "UST_PAR_20Y", "UST_PAR_30Y"}


def test_an_unknown_treasury_column_raises_instead_of_being_skipped():
    text = 'Date,"10 Yr","8 Wk"\n09/25/2026,5.17,4.1\n'
    with pytest.raises(gm.MarketFormatError, match="8 Wk"):
        gm.parse_treasury_par_csv(text)


def test_an_empty_treasury_cell_is_absent_not_zero():
    rows, _ = gm.parse_treasury_par_csv('Date,"10 Yr","30 Yr"\n01/03/2005,4.2,\n')
    assert [r["series_id"] for r in rows] == ["UST_PAR_10Y"]


def test_cboe_vix_ohlc():
    rows, counts = gm.parse_cboe_vix_csv((FIX / "cboe_vix_history_sample.csv").read_text())
    assert counts["kept"] == 20
    close = {r["observation_date"]: r["value"] for r in rows if r["series_id"] == "VIX_CLOSE"}
    assert close[date(2026, 9, 25)] == Decimal("14.870000")
    with pytest.raises(gm.MarketFormatError, match="header"):
        gm.parse_cboe_vix_csv("Date,Close\n01/02/1990,17.24\n")


def test_eia_brent_and_its_contract_checks():
    records = json.loads((FIX / "eia_brent_sample.json").read_text())["response"]["data"]
    rows, counts = gm.parse_eia_spot(records)
    assert counts["kept"] == 6
    assert {r["series_id"] for r in rows} == {"BRENT_SPOT_FOB"}
    assert max(r["observation_date"] for r in rows) == date(2026, 9, 22)
    with pytest.raises(gm.MarketFormatError, match="series"):
        gm.parse_eia_spot([{**records[0], "series": "RWTC"}])
    with pytest.raises(gm.MarketFormatError, match="units"):
        gm.parse_eia_spot([{**records[0], "units": "$/GAL"}])


def test_implausible_market_values_are_dropped_and_counted():
    rows, counts = gm.parse_cboe_vix_csv("DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,0,17.24,17.24,17.24\n")
    assert counts == {"kept": 3, "dropped_invalid": 1}


OFR_CSV = (FIX / "ofr_fsi_sample.csv").read_text()
OFR_XLSX = (FIX / "ofr_fsi_revisions_sample.xlsx").read_bytes()


def test_ofr_fsi_keeps_the_index_and_its_volatility_category():
    rows, counts = gm.parse_ofr_fsi_csv(OFR_CSV)
    assert counts == {"kept": 18, "dropped_invalid": 0}                      # 9 dates, 2 series
    got = {(r["series_id"], r["observation_date"]): r["value"] for r in rows}
    assert got[("OFR_FSI", date(2008, 10, 10))] == Decimal("29.32")          # the series' peak
    assert got[("OFR_FSI_VOLATILITY", date(2026, 9, 23))] == Decimal("-0.488")
    assert {r["unit"] for r in rows} == {"index"} and {r["source"] for r in rows} == {"ofr"}


def test_an_ofr_header_change_raises():
    with pytest.raises(gm.MarketFormatError, match="header"):
        gm.parse_ofr_fsi_csv(OFR_CSV.replace("Volatility", "Vol", 1))
    with pytest.raises(gm.MarketFormatError, match="unreadable date"):
        gm.parse_ofr_fsi_csv(OFR_CSV.splitlines()[0] + "\n09/23/2026" + ",0" * 9 + "\n")


def test_ofr_first_releases_are_the_values_before_each_revision():
    rows, counts = gm.parse_ofr_fsi_revisions(OFR_XLSX)
    first = {(r["series_id"], r["observation_date"]): r["value"] for r in rows}
    assert counts == {"kept": 16, "dropped_invalid": 0}       # 8 dates in the fixture, 2 series
    # 2018 layout (Old / Updated columns) and 2023 layout (Old / New Values blocks).
    assert first[("OFR_FSI_FIRST_RELEASE", date(2017, 10, 2))] == Decimal("-3.605")
    assert first[("OFR_FSI_FIRST_RELEASE", date(2018, 8, 30))] == Decimal("-1.95")
    assert first[("OFR_FSI_FIRST_RELEASE", date(2022, 1, 3))] == Decimal("-2.649")
    assert first[("OFR_FSI_VOLATILITY_FIRST_RELEASE", date(2022, 1, 3))] == Decimal("-0.851")
    # fsi.csv carries the revised values for the same dates.
    now = {(r["series_id"], r["observation_date"]): r["value"] for r in gm.parse_ofr_fsi_csv(OFR_CSV)[0]}
    assert now[("OFR_FSI", date(2017, 10, 2))] == Decimal("-3.455")
    assert now[("OFR_FSI", date(2018, 8, 30))] == Decimal("-2.683")


def test_an_unknown_revision_layout_raises():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Revision 2027-01-15"
    wb.active.append(["Date", "Before", "After"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(gm.MarketFormatError, match="layout"):
        gm.parse_ofr_fsi_revisions(buf.getvalue())
    with pytest.raises(gm.MarketFormatError, match="xlsx"):
        gm.parse_ofr_fsi_revisions(b"<html>moved</html>")


# ---------------------------------------------------------------------------
# MarketIngestor: audit rows, skips, failures, revisions
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, stored):
        self._stored = stored

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.params = params

    def fetchall(self):
        return self._stored


def _ingestor(stored=()):
    client = MagicMock()
    client.cursor.side_effect = lambda: _Cursor(list(stored))
    b3, mkt = MagicMock(), MagicMock()
    return mp.MarketIngestor(b3_fetcher=b3, market_fetcher=mkt, client=client), b3, mkt


def _run(coro):
    return asyncio.run(coro)


def _audit(upsert) -> List[Dict[str, Any]]:
    return [c.args[2][0] for c in upsert.call_args_list if c.args[1] == "cvm_ingest_log"]


def test_a_session_that_is_not_published_is_skipped_and_audited():
    ing, b3, _ = _ingestor()

    async def not_published(session):
        raise B3FileNotPublished("TS260927.ex_: B3 returned an empty archive")
    b3.fetch_taxa_swap.side_effect = not_published
    with patch.object(mp, "upsert_rows") as up:
        assert _run(ing.ingest_reference_rates(date(2026, 9, 28))) == 0
    finish = _audit(up)[-1]
    assert finish["status"] == "skipped" and finish["entity"] == "market"
    assert finish["doc_type"] == "b3_reference_rate"
    assert ing.failures == [] and ing.skips


def test_a_republished_earlier_file_is_skipped_and_stores_nothing():
    ing, b3, _ = _ingestor()

    async def republished(session):
        return TS_2026                                  # the 2026-09-25 file
    b3.fetch_taxa_swap.side_effect = republished
    with patch.object(mp, "upsert_rows") as up:
        assert _run(ing.ingest_reference_rates(date(2026, 9, 28))) == 0
    finish = _audit(up)[-1]
    assert finish["status"] == "skipped" and "republished" in finish["error_msg"]
    assert all(c.args[1] == "cvm_ingest_log" for c in up.call_args_list)
    assert ing.failures == [] and ing.skips


def test_a_parse_failure_is_an_error_row_and_a_collected_failure():
    ing, b3, _ = _ingestor()

    async def broken(session):
        return "short line\n"
    b3.fetch_taxa_swap.side_effect = broken
    with patch.object(mp, "upsert_rows") as up:
        _run(ing.ingest_reference_rates(S_2026))
    assert _audit(up)[-1]["status"] == "error"
    assert len(ing.failures) == 1 and "TaxaSwapFormatError" in ing.failures[0]


def test_reference_rates_land_with_their_natural_key():
    ing, b3, _ = _ingestor()

    async def ok(session):
        return TS_2026
    b3.fetch_taxa_swap.side_effect = ok
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)) as up:
        n = _run(ing.ingest_reference_rates(S_2026))
    data = [c for c in up.call_args_list if c.args[1] == "b3_reference_rate"]
    assert data and data[0].kwargs["conflict_columns"] == "curve,trade_date,calendar_days"
    assert n == len(data[0].args[2]) > 0
    assert _audit(up)[-1]["status"] == "ok"


def test_a_report_without_any_di1_contract_is_an_error_not_an_empty_day():
    ing, b3, _ = _ingestor()

    async def other_only(session):
        return "x.xml", _one_report("DOLV26")
    b3.fetch_price_report.side_effect = other_only
    with patch.object(mp, "upsert_rows"):
        _run(ing.ingest_price_report(S_2026))
    assert ing.failures and "no ('DI1',) contract" in ing.failures[0]


def test_a_revised_value_is_counted_on_the_ok_row():
    stored = [("UST_PAR_10Y", date(2026, 9, 25), Decimal("5.16")),   # revised to 5.17
              ("UST_PAR_2Y", date(2026, 9, 25), Decimal("4.81"))]    # unchanged
    ing, _, mkt = _ingestor(stored)

    async def csv(year):
        return (FIX / "ust_par_yield_2026_sample.csv").read_text()
    mkt.fetch_treasury_year.side_effect = csv
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)) as up:
        _run(ing.ingest_treasury_year(2026))
    finish = _audit(up)[-1]
    assert finish["status"] == "ok"
    assert finish["error_msg"] == "revised 1 stored observations"


def test_backfill_asks_for_weekdays_only_and_never_before_the_source_begins():
    ing, b3, _ = _ingestor()
    asked: List[date] = []

    async def record(session):
        asked.append(session)
        raise B3FileNotPublished("empty")
    b3.fetch_price_report.side_effect = record
    with patch.object(mp, "upsert_rows"):
        _run(ing.backfill(["b3_price_report"], date(2017, 12, 28), date(2018, 1, 7)))
    assert asked == [date(2018, 1, 2), date(2018, 1, 3), date(2018, 1, 4), date(2018, 1, 5)]


def test_unknown_sources_are_refused():
    ing, _, _ = _ingestor()
    with pytest.raises(ValueError, match="unknown market source"):
        _run(ing.backfill(["di1"], date(2020, 1, 1), date(2020, 1, 2)))


def test_the_audit_entity_is_not_b3_so_coverage_never_reads_it_as_cotahist():
    assert mp.LOG_ENTITY == "market"


# ---------------------------------------------------------------------------
# Cboe VIX needs a licence; OFR FSI keeps what was published first
# ---------------------------------------------------------------------------

def _daily_fetchers(b3, mkt):
    async def not_published(session):
        raise B3FileNotPublished("empty")

    async def treasury(year):
        return (FIX / "ust_par_yield_2026_sample.csv").read_text()

    async def eia(start, end):
        return json.loads((FIX / "eia_brent_sample.json").read_text())["response"]["data"]

    async def ofr():
        return OFR_CSV

    async def vix():
        return (FIX / "cboe_vix_history_sample.csv").read_text()
    b3.fetch_price_report.side_effect = not_published
    b3.fetch_taxa_swap.side_effect = not_published
    mkt.fetch_treasury_year.side_effect = treasury
    mkt.fetch_eia_brent.side_effect = eia
    mkt.fetch_ofr_fsi.side_effect = ofr
    mkt.fetch_cboe_vix.side_effect = vix


def test_the_daily_run_never_fetches_vix_without_a_licence(monkeypatch):
    monkeypatch.delenv("CBOE_VIX_LICENSED", raising=False)
    ing, b3, mkt = _ingestor()
    _daily_fetchers(b3, mkt)
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)):
        totals = _run(ing.daily_update(today=date(2026, 9, 27)))
    mkt.fetch_cboe_vix.assert_not_called()
    assert "cboe_vix" not in totals and totals["ofr_fsi"] == 6   # 09-21..23, two series
    assert ing.failures == []
    assert "cboe_vix" not in mp.default_sources()
    with pytest.raises(ValueError, match="licence"):
        _run(ing.backfill(["cboe_vix"], date(2026, 1, 1), date(2026, 1, 2)))


def test_a_licensed_operator_gets_vix(monkeypatch):
    monkeypatch.setenv("CBOE_VIX_LICENSED", "1")
    ing, b3, mkt = _ingestor()
    _daily_fetchers(b3, mkt)
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)):
        totals = _run(ing.daily_update(today=date(2026, 9, 27)))
    mkt.fetch_cboe_vix.assert_called_once()
    assert totals["cboe_vix"] > 0 and "cboe_vix" in mp.default_sources()


def _stored_rows(up, table="mkt_series"):
    return [r for c in up.call_args_list if c.args[1] == table for r in c.args[2]]


def test_an_ofr_backfill_stores_current_values_and_ofrs_first_releases():
    ing, _, mkt = _ingestor()

    async def ofr():
        return OFR_CSV

    async def revisions():
        return OFR_XLSX
    mkt.fetch_ofr_fsi.side_effect = ofr
    mkt.fetch_ofr_fsi_revisions.side_effect = revisions
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)) as up:
        _run(ing.backfill(["ofr_fsi"], date(2017, 1, 1), date(2018, 12, 31)))
    got = {(r["series_id"], r["observation_date"]): r["value"] for r in _stored_rows(up)}
    assert got[("OFR_FSI", date(2017, 10, 2))] == Decimal("-3.455")
    assert got[("OFR_FSI_FIRST_RELEASE", date(2017, 10, 2))] == Decimal("-3.605")
    # The window applies to the workbook too.
    assert not any(d.year == 2022 for _, d in got)
    assert _audit(up)[-1]["status"] == "ok"


def test_a_changed_ofr_value_keeps_the_stored_one_as_its_first_release():
    stored = [("OFR_FSI", date(2026, 9, 23), Decimal("-2.600")),                      # OFR changed it
              ("OFR_FSI", date(2026, 9, 22), Decimal("-2.700")),                      # changed again…
              ("OFR_FSI_FIRST_RELEASE", date(2026, 9, 22), Decimal("-2.750")),        # …first kept already
              ("OFR_FSI_VOLATILITY", date(2026, 9, 23), Decimal("-0.488"))]           # unchanged
    ing, _, mkt = _ingestor(stored)

    async def ofr():
        return OFR_CSV
    mkt.fetch_ofr_fsi.side_effect = ofr
    with patch.object(mp, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: len(rows)) as up:
        _run(ing.ingest_ofr_fsi(date(2026, 9, 1), date(2026, 9, 27)))
    firsts = [r for r in _stored_rows(up) if r["series_id"].endswith("_FIRST_RELEASE")]
    assert [(r["series_id"], r["observation_date"], r["value"]) for r in firsts] == [
        ("OFR_FSI_FIRST_RELEASE", date(2026, 9, 23), Decimal("-2.600"))]
    assert _audit(up)[-1]["error_msg"] == (
        "revised 2 stored observations; kept 1 superseded values as first releases")


# ---------------------------------------------------------------------------
# IC-Br rides the SGS fetch without joining api.macro_series' registry
# ---------------------------------------------------------------------------

def test_icbr_is_fetched_with_sgs_but_kept_out_of_the_served_registry():
    from src.pipeline import bacen_pipeline as bp

    assert set(bp.RESEARCH_SGS_SERIES.values()) == {27574, 27575, 27576, 27577}
    assert not set(bp.RESEARCH_SGS_SERIES) & set(bp.SGS_SERIES)
    with patch.object(bp, "get_pg_client"), patch.object(bp, "upsert_rows", return_value=0), \
         patch.object(bp.BacenIngestor, "_last_sgs_landing", return_value=None):
        ing = bp.BacenIngestor()
        seen = {}

        async def fake(codes, start=None, end=None, last=None):
            seen.update(codes)
            return [{"date": "2026-08-01", "ICBR": 456.24}]
        ing._client.get_sgs_series = fake
        _run(ing.ingest_sgs("2026-08-01", "2026-09-27"))
    assert seen["ICBR"] == 27574 and seen["SELIC_META"] == 432
