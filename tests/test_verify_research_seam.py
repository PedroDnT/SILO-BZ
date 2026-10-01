"""The research-seam verification script (#420) judges correctly, offline.

The script runs against the live API, which cannot be reached from the test
suite, so a small simulator of the documented interface stands in. Each test
either runs the whole script against a healthy simulator (every requirement
READY) or switches ONE defect on and requires the matching requirement to turn
NOT READY and name the defect. A verifier that cannot fail is not a verifier.
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

_spec = importlib.util.spec_from_file_location(
    "verify_research_seam", ROOT / "docs/reference/research/verify_research_seam.py")
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


def _interp(date: str) -> float:
    """TR / adjusted: 0.45 at the start of the tape, 0.6875 on 2023-12-28, 1.0 on the last session."""
    pts = [("2019-01-02", 0.45), ("2023-12-28", 0.6875), (LAST, 1.0)]
    x = dt.date.fromisoformat(date).toordinal()
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        a, b = dt.date.fromisoformat(d0).toordinal(), dt.date.fromisoformat(d1).toordinal()
        if a <= x <= b:
            return v0 + (v1 - v0) * (x - a) / (b - a)
    return 1.0


def _row(ticker, date, close, adj=None, reason=None, tr=None, tr_reason=None, cls="equity"):
    return {"ticker": ticker, "trade_date": date, "close": close, "adjusted": False,
            "asset_class": cls, "close_price_adjusted": adj,
            "close_price_adjusted_null_reason": reason,
            "close_total_return": tr, "close_total_return_null_reason": tr_reason}


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
            rows.append({"ticker": t, "isin": f"BR{t[:4]}ACNOR{i % 10}", "instrument_type": "equity",
                         "cnpj": f"{i:014d}", "cnpj_basis": "fca_issuer_stem" if i % 7 == 0 else "fca_ticker",
                         "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 1900 - i})
        rows += [
            {"ticker": "PETR4", "isin": "BRPETRACNPR6", "instrument_type": "equity", "cnpj": "33000167000101",
             "cnpj_basis": "fca_ticker", "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 1960},
            {"ticker": "VALE3", "isin": "BRVALEACNOR0", "instrument_type": "equity", "cnpj": "33592510000154",
             "cnpj_basis": "fca_ticker", "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 1959},
            {"ticker": "NATU3", "isin": "BRNATUACNOR6", "instrument_type": "equity", "cnpj": "71673990000177",
             "cnpj_basis": "fca_ticker", "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 554},
            {"ticker": "ELET3", "isin": "BRELETACNOR6", "instrument_type": "equity", "cnpj": "00001180000126",
             "cnpj_basis": "fca_ticker", "first_observed": "2019-01-02", "last_observed": "2025-11-07", "n_sessions": 1709},
            {"ticker": "AXIA3", "isin": "BRAXIAACNOR0", "instrument_type": "equity", "cnpj": "00001180000126",
             "cnpj_basis": "fca_ticker", "first_observed": "2025-11-10", "last_observed": LAST, "n_sessions": 220},
        ]
        if self.defects.get("receipt"):
            rows.append({"ticker": "XXXX9", "isin": "BRXXXXR01001", "instrument_type": "equity", "cnpj": None,
                         "cnpj_basis": None, "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 9})
        if self.defects.get("natu3_two_rows"):
            rows.append(dict(next(r for r in rows if r["ticker"] == "NATU3"), isin="BRNATUACNOR7"))
        if self.defects.get("stem_two_cnpj"):
            rows.append({"ticker": "AAXX4", "isin": "BRAAXXACNPR1", "instrument_type": "equity",
                         "cnpj": "99999999999999", "cnpj_basis": "fca_issuer_stem",
                         "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 100})
        if self.defects.get("index_in_universe"):
            rows.append({"ticker": "IBOV11", "isin": "BRIBOVACNOR1", "instrument_type": "unit", "cnpj": None,
                         "cnpj_basis": None, "first_observed": "2019-01-02", "last_observed": LAST, "n_sessions": 50})
        return rows

    def research_universe(self, as_of=None):
        if as_of is None:
            return list(self.universe)
        return [r for r in self.universe if r["first_observed"] <= as_of <= r["last_observed"]]

    # -- quotes -------------------------------------------------------------
    def _series(self, ticker, start, end):
        out = []
        for d in weekdays(max(start, "2019-01-02"), end):
            ratio = _interp(d)
            adj = 20.0 + len(out) * 0.001
            tr = adj * ratio
            if self.defects.get("tr_above_adjusted") and d == "2021-03-01":
                tr = adj * 1.2
            r = _row(ticker, d, adj, adj, None, tr, None)
            if self.defects.get("null_without_reason") and ticker == "PETR4" and d == end:
                r.update(close_price_adjusted=None)
            out.append(r)
        return out

    def quote_history(self, ticker, start=None, end=None, board=None):
        start = str(start or (TODAY - dt.timedelta(days=365)).isoformat())
        end = str(end or TODAY.isoformat())
        if start < "2019-01-02" and not self.defects.get("no_window_refusal"):
            raise SiloError(400, '{"code":"22023","message":"quote_history: refused, p_from %s is before the '
                                 'start of the tape (2019-01-02)."}' % start, "u")
        if ticker == "ZZZZ9":
            return [{"ticker": "ZZZZ9"}] if self.defects.get("guessed_row") else []
        if ticker == "BBAS3" and start == "2024-04-10":
            adj_a = 56.46 if self.defects.get("adjusted_equals_raw") else 28.23
            adj_b = 27.91
            days = {"2024-04-10": 55.0, "2024-04-11": 55.5, "2024-04-12": 56.0, "2024-04-15": 56.46,
                    "2024-04-16": 27.91, "2024-04-17": 27.5, "2024-04-18": 27.7, "2024-04-19": 27.8}
            return [_row("BBAS3", d, c, (adj_a if d == "2024-04-15" else (adj_b if d == "2024-04-16" else c / 2)))
                    for d, c in days.items()]
        if ticker == "MGLU3" and start == "2024-05-20":
            days = {"2024-05-20": 1.30, "2024-05-24": 1.32, "2024-05-27": 13.20, "2024-05-28": 13.1}
            return [_row("MGLU3", d, c, (13.2 if d in ("2024-05-24", "2024-05-27") else c * 10)) for d, c in days.items()]
        if ticker == "IBOV11":
            levels = {r["trade_date"]: r["level"] for r in self._ibov()}
            dates = [d for d in weekdays(max(start, "2025-01-02"), end) if d in levels]
            out = []
            for i, d in enumerate(dates):
                close = levels[d] if self.defects.get("ibov11_equals_index") else levels[d] * (1.0015 + 0.0005 * (i % 3))
                out.append(_row("IBOV11", d, close, None, "outside research universe", None,
                                "outside research universe", "index"))
            return out
        if ticker == "BOVA11":
            adj = 1.0 if self.defects.get("etf_adjusted") else None
            reason = None if adj else "outside research universe"
            dates = list(weekdays("2025-01-02", "2026-09-29"))[:400]
            return [_row("BOVA11", d, 100.0, adj, reason, None, "outside research universe", "fund_quota")
                    for d in dates]
        if start == "2023-12-28" and end == "2023-12-28":
            return [{**self._series(ticker, "2023-12-28", "2023-12-28")[0]}]
        rows = self._series(ticker, start, end)
        if len(rows) > 1000 and not self.defects.get("no_row_cap"):
            raise SiloOverCap('{"code":"22023","message":"refused, this request would return more than 1000 rows"}', "u")
        if self.defects.get("window_not_served") and start == "2019-01-02" and end == "2019-01-31":
            return []
        return rows

    def quote_history_all(self, ticker, start=None, end=None, board=None):
        return self._series(ticker, str(start or "2019-01-02"), str(end or TODAY.isoformat()))

    def quote_history_many(self, tickers, start=None, end=None, board=None, *, workers=8, require_rows=False):
        out = {}
        for t in tickers:
            rows = self._series(t, "2019-01-02", LAST) if t in ("PETR4", "VALE3") else self._series(t, "2026-09-01", LAST)
            if self.defects.get("fanout_empty") and t == tickers[3]:
                rows = []
            out[t] = rows
        empty = [t for t, r in out.items() if not r]
        if require_rows and empty:
            from silo_client import SiloFanOutError
            raise SiloFanOutError({}, out, empty)
        return out

    # -- index --------------------------------------------------------------
    def index_history(self, index, start=None, end=None):
        if index != "IBOV" and not self.defects.get("ticker_substitutes"):
            raise SiloError(400, '{"code":"22023","message":"index_history: p_index must be a B3 index code '
                                 'SILO holds (IBOV), got %s"}' % index, "u")
        if index != "IBOV":
            return [{"index_code": index, "trade_date": "2025-12-30", "level": 1.0, "divisor_step": False}]
        start, end = str(start or "2025-09-30"), str(end or TODAY.isoformat())
        rows = self._ibov()
        sel = [r for r in rows if start <= r["trade_date"] <= end]
        if len(sel) > 1000 and not self.defects.get("no_index_cap"):
            raise SiloOverCap('{"code":"22023","message":"more than 1000 rows"}', "u")
        return sel

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

    def iter_index_history(self, index, start=None, end=None):
        return iter(self.index_history_all(index, start, end))

    def index_history_all(self, index, start=None, end=None):
        if index != "IBOV":
            return self.index_history(index)
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
            key = (ref, doc)
            if key not in best or ver > best[key][2]:
                best[key] = (ref, doc, ver, recv)
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

    # -- macro, catalog, coverage -------------------------------------------
    def macro_series(self, series, start=None, end=None):
        start, end = str(start), str(end)
        rows = [{"reference_date": d, "value": 0.04} for d in weekdays(start, end)]
        if len(rows) > 1000 and not self.defects.get("no_macro_cap"):
            raise SiloOverCap('{"code":"22023","message":"more than 1000 rows"}', "u")
        return rows

    def catalog(self, refresh=False):
        return {"version": 47 if self.defects.get("old_catalog") else 48}

    def coverage(self):
        note = None if self.defects.get("no_tape_note") else "the tape starts 2019-01-02: api.quote_history raises 22023"
        return [{"dataset": "quotes", "notes": note},
                {"dataset": "index_history", "notes": "IBOV from 1968-01-02"}]


def run(**defects):
    board = defects.pop("board", None)
    fake = FakeSilo(**defects)
    return vrs.run_all(fake, n=100, workers=4, today=TODAY, board_query=board)


def by(results, req):
    return [r for r in results if r.requirement == req]


def failing(results):
    return {(r.requirement, r.check) for r in results if r.status == "FAIL"}


def test_a_healthy_interface_is_ready_once_the_board_query_has_run():
    results = run(board=lambda: [])
    bad = [r for r in results if r.status != "PASS"]
    assert not bad, [(r.requirement, r.check, r.evidence) for r in bad]
    assert vrs.overall(results) == "READY"
    assert set(vrs.verdicts(results).values()) == {"READY"}


def test_without_database_access_the_board_requirement_is_not_run_and_the_whole_is_not_ready():
    results = run()
    r7 = by(results, "R7")
    assert [r.status for r in r7] == ["NOT RUN"]
    assert "SELECT" in r7[0].evidence and "mv_research_universe" in r7[0].evidence
    assert vrs.verdicts(results)["R7"] == "NOT READY"
    assert vrs.overall(results) == "NOT READY"


def test_tickers_on_more_than_one_board_make_the_requirement_not_ready_pending_the_owner():
    rows = [{"ticker": "BRKM5", "boards": "02/07", "sessions": 1929},
            {"ticker": "AALR3", "boards": "02/07", "sessions": 1929}]
    results = run(board=lambda: rows)
    r7 = by(results, "R7")
    assert r7[0].status == "FAIL"
    assert "BRKM5" in r7[0].evidence and "OWNER DECISION PENDING" in r7[0].evidence
    assert vrs.verdicts(results)["R7"] == "NOT READY"
    assert vrs.overall(results) == "NOT READY"
    # and only R7: the rest of the seam is unaffected
    assert {v for k, v in vrs.verdicts(results).items() if k != "R7"} == {"READY"}


@pytest.mark.parametrize("defect,requirement,needle", [
    ("receipt", "R1", "no R## receipt"),
    ("natu3_two_rows", "R1", "NATU3"),
    ("stem_two_cnpj", "R1", "fca_issuer_stem"),
    ("index_in_universe", "R1", "outside the universe"),
    ("adjusted_equals_raw", "R2", "BBAS3"),
    ("etf_adjusted", "R2", "other classes"),
    ("tr_above_adjusted", "R3", "total return <= adjusted"),
    ("ticker_substitutes", "R4", "never substitutes"),
    ("missing_step", "R4", "divisor steps"),
    ("no_index_cap", "R4", "refuses instead of trimming"),
    ("ibov11_equals_index", "R4", "never equals the official close"),
    ("leak", "R5", "no line from a filing received"),
    ("sibling_ignores_as_of", "R5", "honour as_of"),
    ("no_window_refusal", "R6", "before 2019-01-02"),
    ("guessed_row", "R6", "unknown ticker"),
    ("no_tape_note", "R6", "coverage()"),
    ("no_row_cap", "R6", "over the row cap"),
    ("fanout_empty", "R8", "the whole request"),
    ("null_without_reason", "R8", "every NULL carries a reason"),
    ("no_macro_cap", "R9", "whole window refuses"),
    ("old_catalog", "R10", "catalog version"),
])
def test_each_defect_turns_its_requirement_not_ready_and_is_named(defect, requirement, needle):
    results = run(board=lambda: [], **{defect: True})
    hit = [r for r in by(results, requirement) if r.status == "FAIL" and needle in r.check]
    assert hit, (defect, [(r.check, r.status) for r in by(results, requirement)])
    assert vrs.verdicts(results)[requirement] == "NOT READY"
    assert vrs.overall(results) == "NOT READY"


def test_a_check_that_raises_is_a_fail_with_the_exception_never_a_skip():
    class Broken(FakeSilo):
        def index_history(self, *a, **k):
            raise RuntimeError("boom")

    results = vrs.run_all(Broken(), n=100, workers=2, today=TODAY, board_query=lambda: [])
    r4 = [r for r in by(results, "R4") if r.status == "FAIL"]
    assert r4 and any("RuntimeError: boom" in r.evidence for r in r4)
    assert vrs.verdicts(results)["R4"] == "NOT READY"


def test_the_report_names_every_requirement_with_a_verdict_and_both_clocks():
    results = run(board=lambda: [])
    text = vrs.render_markdown(results, now=dt.datetime(2026, 10, 1, 8, 5, tzinfo=dt.timezone.utc))
    assert "Research seam verification: **READY**" in text
    assert "05:05 UTC-3 (08:05 UTC)" in text
    for req, title in vrs.REQUIREMENTS.items():
        assert f"{req} {title}" in text
    assert text.count("**READY**") >= len(vrs.REQUIREMENTS)


def test_the_board_sql_reads_the_universe_and_only_the_cash_market_since_the_tape_start():
    sql = vrs.BOARD_SQL
    assert "mv_research_universe" in sql and "tpmerc = '010'" in sql
    assert "DATE '2019-01-02'" in sql and "HAVING count(DISTINCT b.codbdi) > 1" in sql
    assert not any(w in sql.upper() for w in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"))


def test_the_script_never_writes_and_uses_only_the_public_sdk():
    src = (ROOT / "docs/reference/research/verify_research_seam.py").read_text(encoding="utf-8")
    assert "from silo_client import" in src
    # the only database access is the read-only board query behind --db-url
    assert src.count("cur.execute(") == 2 and "SET statement_timeout" in src
