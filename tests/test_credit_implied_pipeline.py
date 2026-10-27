"""Offline checks of the implied-rate pipeline and the holiday parser (#1007)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from src.credit.implied_rate import Calendar
from src.parsers import anbima_holidays as H
from src.pipeline import credit_implied_pipeline as P
from src.pipeline import ingest_log

HOLS = [date(y, 1, 1) for y in range(2024, 2036)] + [date(y, 12, 25) for y in range(2024, 2036)]
CAL = Calendar(HOLS)
T = date(2026, 1, 2)
V = date(2027, 1, 4)
CAPTURE = "11111111-1111-1111-1111-111111111111"


class FakeCursor:
    def __init__(self, db): self.db, self.rows = db, []

    def execute(self, sql, params=None):
        for needle, rows in self.db.answers:
            if needle in sql:
                self.rows = rows(params) if callable(rows) else rows
                return
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def fetchall(self): return self.rows


class FakeDb:
    def __init__(self, answers): self.answers = answers

    @contextmanager
    def cursor(self): yield FakeCursor(self)


def pre_rows(bd_shift=0):
    return [("PRE", CAL.du(T, T + timedelta(days=cd)) + bd_shift, cd, 10.0) for cd in (30, 90, 365, 800, 1500)]


def answers(trades, pre=None, holidays=None):
    return [
        ("FROM anbima_holiday", [(d,) for d in HOLS] if holidays is None else holidays),
        ("FROM anbima_debenture d", [("TEST11", "PRE", "prefixado", 12.0, 1000, T, V)]),
        ("FROM anbima_debenture_event e", [
            ("TEST11", V, "Pagamento de juros", V, 12.0), ("TEST11", V, "Vencimento (resgate)", V, 100.0)]),
        ("FROM b3_credit_capture", trades),
        ("series_code = 12", []),
        ("series_code = 433", []),
        ("FROM bacen_expectativas", []),
        ("FROM b3_reference_rate", pre_rows() if pre is None else pre),
    ]


def trade_rows(code="TEST11", pu=1000.0, td=T):
    k = (CAPTURE, code, td, td, "EXTRAGRUPO")
    return [(*k, "avg_price", pu), (*k, "quantity", 10), (*k, "volume_brl", pu * 10), (*k, "trade_count", 2)]


def run(db, **kw):
    upserts = []
    with patch.object(P, "upsert_rows", side_effect=lambda c, t, rows, conflict_columns=None: (
            upserts.append((t, rows, conflict_columns)) or len(rows))):
        ing = P.CreditImpliedIngestor(conn=db)
        out = ing._run(T, T, kw.get("codes"), kw.get("refresh", False))
    return out, upserts


def test_a_priced_trade_becomes_one_calculated_row_with_its_inputs():
    out, ups = run(FakeDb(answers(trade_rows(pu=1000.0))))
    (table, rows, key), = ups
    assert table == "b3_credit_implied_rate"
    assert key == "codigo,trade_date,settlement_date,trade_classification,method_version"
    r, = rows
    assert (r["codigo"], r["method_version"], r["is_calculated"], r["rate_basis"]) == ("TEST11", "v1", True, "pre_aa")
    assert r["implied_rate_pct"] == pytest.approx(12.0, abs=1e-8)  # par PU at the contract rate
    assert r["b3_capture_id"] == CAPTURE and r["pu_brl"] == 1000.0 and r["quantity"] == 10
    assert r["trade_count"] == 2 and r["flows_used"] == 1
    assert r["inputs"]["curve_date"] == "2026-01-02" and "residual_brl" in r["solver"]
    assert out.status == "ok" and out.rows == 1 and "1 priced" in out.error


def test_reasons_are_counted_and_unpriced_trades_write_no_row():
    rows = trade_rows() + trade_rows(code="OTHER1", pu=500.0)
    out, ups = run(FakeDb(answers(rows)), codes=["TEST11", "OTHER1"])
    assert len(ups[0][1]) == 1
    assert "no_schedule=1" in out.error and "1 priced" in out.error


def test_nothing_priced_fails_the_run():
    with pytest.raises(ingest_log.PartialIngestError) as e:
        run(FakeDb(answers(trade_rows(pu=0.0))))
    assert "pu_invalid=1" in str(e.value)


def test_a_holiday_list_that_disagrees_with_b3_fails_the_trade_date():
    with pytest.raises(ingest_log.PartialIngestError) as e:
        run(FakeDb(answers(trade_rows(), pre=pre_rows(bd_shift=1))))
    assert "calendar_mismatch=1" in str(e.value)


def test_a_missing_curve_is_counted_not_guessed():
    with pytest.raises(ingest_log.PartialIngestError) as e:
        run(FakeDb(answers(trade_rows(), pre=[])))
    assert "curve_missing=1" in str(e.value)


def test_an_empty_holiday_table_is_filled_from_ANBIMA_before_pricing():
    fetched = [{"holiday_date": d, "name": "x", "source_url": H.SOURCE_URL} for d in HOLS]
    with patch.object(P, "fetch_holidays", return_value=fetched):
        out, ups = run(FakeDb(answers(trade_rows(), holidays=[])))
    assert ups[0][0] == "anbima_holiday" and ups[0][2] == "holiday_date"
    assert all("observed_at" in r for r in ups[0][1])
    assert ups[1][0] == "b3_credit_implied_rate"


def test_holiday_parser_reads_dates_and_stops_at_the_footnotes():
    rows = [("Data", "Dia da Semana", "Feriado"),
            (datetime(2026, 1, 1), "quinta-feira", "Confraternização Universal"),
            (datetime(2079, 4, 21), "sexta-feira", "Paixão de Cristo"),
            (datetime(2079, 4, 21), "sexta-feira", "Tiradentes"),
            ("Notas:", None, None), (datetime(2099, 1, 1), "x", "after the notes")]
    out = H.parse_holidays(rows)
    assert [r["holiday_date"] for r in out] == [date(2026, 1, 1), date(2079, 4, 21)]
    assert out[1]["name"] == "Paixão de Cristo / Tiradentes"


def test_holiday_parser_refuses_a_changed_sheet():
    with pytest.raises(H.HolidayParseError):
        H.parse_holidays([("Dia", "x", "y"), (datetime(2026, 1, 1), "x", "y")])
    with pytest.raises(H.HolidayParseError):
        H.parse_holidays([("Data", "x", "y")])
