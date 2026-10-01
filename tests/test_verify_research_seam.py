"""scripts/verify_research_seam.py judges the rest of the spec's test list correctly (#420).

The script runs against the live API, which the offline suite cannot reach, so a
small simulator of the documented interface stands in. A healthy simulator must
produce no problem line (with the 6-decimal rounding real levels carry), and each
test switches ONE defect on and requires the matching line to fail. A verifier that
cannot fail is not a verifier.

Only the sections added for #420 are driven here (`run_extras`); the first list
(ETER3, the page edge, close_adj pins) is #461's and is proven on the live API.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from silo_client import SiloError, SiloOverCap  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_research_seam", ROOT / "scripts/verify_research_seam.py")
vrs = importlib.util.module_from_spec(_spec)
sys.modules["verify_research_seam"] = vrs
_spec.loader.exec_module(vrs)

TODAY = dt.date(2026, 9, 30)
LAST = "2026-09-29"


def weekdays(a: str, b: str):
    d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += dt.timedelta(days=1)


def _ratio(date: str) -> float:
    """total return / close_adj, flat between ex-dates like the real one: it can only rise, in steps,
    to 1.0 on the last session (0.6875 on 2023-12-28, the value measured on 2026-09-30)."""
    steps = [("2019-01-02", 0.45), ("2020-06-01", 0.50), ("2021-06-01", 0.56), ("2022-06-01", 0.62),
             ("2023-06-01", 0.6875), ("2024-06-01", 0.80), ("2025-06-01", 0.90), ("2026-06-01", 1.0)]
    level = steps[0][1]
    for start, value in steps:
        if date >= start:
            level = value
    return level


class FakeSilo:
    """The documented public interface, in memory, with switchable defects."""

    def __init__(self, **defects):
        self.defects = defects
        self.universe = self._universe()

    # -- universe -----------------------------------------------------------
    def _universe(self):
        rows = []
        for i in range(400):
            t = f"{chr(65 + i // 26 % 26)}{chr(65 + i % 26)}XX3"
            rows.append({"ticker": t, "isin": f"BR{t[:4]}ACNOR{i % 10}", "cnpj": f"{i:014d}",
                         "cnpj_basis": "fca_issuer_stem" if i % 7 == 0 else "fca_ticker",
                         "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 1900 - i})
        rows += [
            {"ticker": "PETR4", "isin": "BRPETRACNPR6", "cnpj": "33000167000101", "cnpj_basis": "fca_ticker",
             "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 1960},
            {"ticker": "NATU3", "isin": "BRNATUACNOR6", "cnpj": "71673990000177", "cnpj_basis": "fca_ticker",
             "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 554},
            {"ticker": "ELET3", "isin": "BRELETACNOR6", "cnpj": "00001180000126", "cnpj_basis": "fca_ticker",
             "first_observed": "2019-01-02", "last_observed": "2025-11-07", "n_sessions": 1709},
            {"ticker": "AXIA3", "isin": "BRAXIAACNOR0", "cnpj": "00001180000126", "cnpj_basis": "fca_ticker",
             "first_observed": "2025-11-10", "last_observed": LAST, "n_sessions": 220},
        ]
        if self.defects.get("receipt"):
            rows.append({"ticker": "XXXX9", "isin": "BRXXXXR01001", "cnpj": None, "cnpj_basis": None,
                         "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 9})
        if self.defects.get("natu3_two_rows"):
            rows.append(dict(next(r for r in rows if r["ticker"] == "NATU3"), isin="BRNATUACNOR7"))
        if self.defects.get("stem_two_cnpj"):
            rows.append({"ticker": "AAXX4", "isin": "BRAAXXACNPR1", "cnpj": "99999999999999",
                         "cnpj_basis": "fca_issuer_stem", "first_observed": "2019-01-02",
                         "last_observed": LAST, "n_sessions": 100})
        if self.defects.get("index_in_universe"):
            rows.append({"ticker": "IBOV11", "isin": "BRIBOVACNOR1", "cnpj": None, "cnpj_basis": None,
                         "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 50})
        return rows

    def research_universe(self, as_of=None):
        if as_of is None or self.defects.get("as_of_ignored"):
            return list(self.universe)
        return [r for r in self.universe if r["first_observed"] <= as_of <= r["last_observed"]]

    # -- quotes -------------------------------------------------------------
    def _petr4(self, start, end):
        out = []
        for i, d in enumerate(d for d in weekdays(max(start, "2019-01-02"), end)):
            adj = round(20.0 + (i % 50) * 0.137, 6)            # 6 decimals, like the real levels
            ratio = _ratio(d)
            if self.defects.get("tr_above_adjusted") and d == "2021-03-01":
                ratio = 1.2
            if self.defects.get("tr_ratio_falls") and d == "2022-06-01":
                ratio *= 0.9
            tr = round(adj * ratio, 6)
            if self.defects.get("tr_last_differs") and d == LAST:
                tr = round(adj * 0.98, 6)
            row = {"ticker": "PETR4", "trade_date": d, "close_adj": adj, "close_total_return": tr,
                   "close_total_return_null_reason": None}
            if self.defects.get("tr_null") and d == "2023-12-28":
                row.update(close_total_return=None, close_total_return_null_reason="issuer corporate events not proven swept")
            out.append(row)
        return out

    def quote_history(self, ticker, start=None, end=None, board=None, fields=None):
        start, end = str(start), str(end)
        if ticker == "PETR4":
            return self._petr4(start, end)
        raise AssertionError(f"unexpected quote_history call: {ticker}")

    def quote_history_all(self, ticker, start=None, end=None, board=None, fields=None):
        start, end = str(start or "2019-01-02"), str(end or LAST)
        if ticker == "PETR4":
            return self._petr4(start, min(end, LAST))
        if ticker == "IBOV11":
            levels = {r["trade_date"]: r["level"] for r in self._ibov()}
            dates = [d for d in weekdays(start, end) if d in levels]
            return [{"ticker": "IBOV11", "trade_date": d,
                     "close": levels[d] if self.defects.get("ibov11_equals_index") else levels[d] * (1.0015 + 0.0005 * (i % 3)),
                     "asset_class": "index"} for i, d in enumerate(dates)]
        raise AssertionError(f"unexpected quote_history_all call: {ticker}")

    # -- index --------------------------------------------------------------
    def _ibov(self):
        steps = set(vrs.IBOV_DIVISOR_STEPS)
        if self.defects.get("missing_step"):
            steps.discard("1985-12-03")
        rows = []
        for d in weekdays("1968-01-02", LAST):
            level = 161125.37 if d == "2025-12-30" else 1000.0 + len(rows) * 0.01
            rows.append({"index_code": "IBOV", "trade_date": d, "level": level,
                         "divisor_step": d in steps, "source": "b3_index_statistics"})
        return rows

    def index_history(self, index, start=None, end=None):
        if index != "IBOV":
            if self.defects.get("ticker_substitutes"):
                return [{"index_code": index, "trade_date": "2025-12-30", "level": 1.0, "divisor_step": False}]
            raise SiloError(400, '{"code":"22023","message":"index_history: p_index must be a B3 index code"}', "u")
        start, end = str(start or "2025-09-30"), str(end or TODAY.isoformat())
        rows = [r for r in self._ibov() if start <= r["trade_date"] <= end]
        if len(rows) > 1000 and not self.defects.get("no_index_cap"):
            raise SiloOverCap('{"code":"22023","message":"more than 1000 rows"}', "u")
        return rows

    def index_history_all(self, index, start=None, end=None):
        return [r for r in self._ibov() if str(start or "1968-01-02") <= r["trade_date"] <= str(end or LAST)]

    # -- fundamentals -------------------------------------------------------
    DOCS = [("2023-09-30", "itr", 1, "2023-11-09"), ("2023-12-31", "dfp", 1, "2024-03-08"),
            ("2023-12-31", "dfp", 2, "2024-03-25"), ("2024-03-31", "itr", 1, "2024-05-09")]

    def _visible(self, as_of):
        docs = list(self.DOCS)
        if as_of is not None and not self.defects.get("leak"):
            docs = [d for d in docs if d[3] < as_of]
        best = {}
        for ref, doc, ver, recv in docs:
            if (ref, doc) not in best or ver > best[(ref, doc)][2]:
                best[(ref, doc)] = (ref, doc, ver, recv)
        return sorted(best.values())

    def financials(self, id, statement=None, start=None, end=None, scope="con", doc_type=None, as_of=None):
        return [{"ref_date": ref, "doc_type": doc, "version": ver, "account_code": "3.01", "value": 1.0}
                for ref, doc, ver, _ in self._visible(as_of) if str(start or "") <= ref <= str(end or "9999")]

    def company_financials(self, id, start=None, end=None, scope="con", as_of=None):
        if self.defects.get("sibling_ignores_as_of"):
            as_of = None
        return [{"ref_date": ref, "doc_type": doc, "version": ver, "revenue": 1.0}
                for ref, doc, ver, _ in self._visible(as_of) if str(start or "") <= ref <= str(end or "9999")]

    def income_statements(self, id, start=None, end=None, scope="con", doc_type=None, as_of=None):
        return self.company_financials(id, start, end, scope, as_of)

    def financial_statement_history(self, id, statement, start=None, end=None, scope="con", doc_type=None):
        return [{"ref_date": ref, "doc_type": doc, "version": ver, "filing_received_date": recv}
                for ref, doc, ver, recv in sorted(self.DOCS) if str(start or "") <= ref <= str(end or "9999")]

    # -- macro and coverage ---------------------------------------------------
    def macro_series(self, series, start=None, end=None):
        rows = [{"reference_date": d, "value": 0.04} for d in weekdays(str(start), str(end))]
        if len(rows) > 1000 and not self.defects.get("no_macro_cap"):
            raise SiloOverCap('{"code":"22023","message":"more than 1000 rows"}', "u")
        return rows

    def coverage(self):
        note = ("B3 COTAHIST cash tape from 2019-01-02. quote_history refuses a window that starts before an "
                "instrument's first session" if not self.defects.get("no_tape_note") else "")
        return [{"dataset": "quotes", "notes": note}, {"dataset": "index_history", "notes": "IBOV from 1968-01-02"}]


@pytest.fixture(autouse=True)
def _clock_and_problems(monkeypatch):
    monkeypatch.setattr(vrs, "_today", lambda: TODAY)
    vrs.problems.clear()
    yield
    vrs.problems.clear()


def run(silo=None, **defects):
    vrs.problems.clear()
    vrs.run_extras(silo or FakeSilo(**defects))
    return list(vrs.problems)


def test_a_healthy_interface_has_no_problem_line_even_with_six_decimal_levels():
    assert run() == []


@pytest.mark.parametrize("defect,needle", [
    ("receipt", "only shares and units"),
    ("index_in_universe", "BOVA11 and IBOV11 are not in it"),
    ("natu3_two_rows", "NATU3 is 2 row(s)"),
    ("stem_two_cnpj", "fca_issuer_stem stems, each with one CNPJ"),
    ("as_of_ignored", "a rename is two rows"),
    ("tr_null", "has no level"),
    ("tr_above_adjusted", "never above close_adj"),
    ("tr_ratio_falls", "the ratio never falls"),
    ("tr_last_differs", "equal on the latest session"),
    ("missing_step", "divisor steps flagged"),
    ("ticker_substitutes", "index_history refuses BOVA11"),
    ("no_index_cap", "a 14,000-row window refuses instead of trimming"),
    ("ibov11_equals_index", "a settlement index, never the benchmark"),
    ("leak", "none from a filing received on or after 2024-02-29"),
    ("sibling_ignores_as_of", "company_financials honours as_of"),
    ("no_macro_cap", "the whole seven-year window refuses"),
    ("no_tape_note", "the quotes row names the tape start"),
])
def test_each_defect_fails_its_line_and_names_it(defect, needle):
    problems = run(**{defect: True})
    assert any(needle in p for p in problems), (defect, problems)


def test_a_crash_in_one_section_is_a_fail_line_and_the_other_sections_still_run():
    class Broken(FakeSilo):
        def index_history_all(self, *a, **k):
            raise RuntimeError("boom")

    problems = run(Broken(leak=True))
    assert any("benchmark: stopped by RuntimeError: boom" in p for p in problems)
    # the as-of section after it still ran and still caught its own defect
    assert any("none from a filing received on or after" in p for p in problems)


def test_the_tolerances_catch_a_real_fall_and_ignore_rounding():
    # one distribution moves the ratio about 0.5%; six-decimal rounding moves it about 1e-7
    assert run(tr_ratio_falls=True), "a 10% fall in the ratio must be caught"
    assert run() == [], "rounding noise must not be"


def test_the_script_uses_only_the_public_sdk_and_never_a_database():
    src = (ROOT / "scripts/verify_research_seam.py").read_text(encoding="utf-8")
    assert "from silo_client import" in src
    for forbidden in ("psycopg2", "POSTGRES_URL", "cur.execute", "requests.post("):
        assert forbidden not in src
