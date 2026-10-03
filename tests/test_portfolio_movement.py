"""Movimento incomum (block 14b), offline: the FakeClient answers from canned api.portfolio_movement rows.

The statistics are the SQL's (executed in tests/sql/portfolio_behaviour.sql: winsorization at the class's 1st and 99th
percentile, the minimum of 30 peers, the thresholds). What this file keeps true is the engine's side of the owner's
decisions of 2026-10-03 (map #510): strictly beyond 2 class standard deviations is `atencao` (table only), strictly
beyond 3 is `forte` (text, and the Investigator flag); a fund the SQL could not judge is `nao_avaliado` with the reason,
never skipped and never normal; the engine states the number, the class, the sample size and the month, and recomputes
none of it.
"""

from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.diagnose import FAKE_CLOCK
from src.portfolio.engine import default_params, run_engine
from src.portfolio.movement import (
    ATENCAO,
    FORTE,
    NORMAL,
    NOT_EVALUATED,
    classify_z,
    default_movement_month,
)
from src.portfolio.statement import read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"

GERACAO = "08935128000159"  # the fixture's atencao fund
XP_FIC = "50088190000119"  # not in the Extrato: no class
XP_LIQ = "51488342000133"  # the fixture's forte fund


def canned_with(rows_fn=None):
    canned = load_fake_rows(FAKE_ROWS)
    if rows_fn is not None:
        entry = canned["portfolio_movement"][0]
        entry["rows"] = rows_fn(copy.deepcopy(entry["rows"]))
    return canned


def run(canned=None):
    stmt = read_statement(TEMPLATE)
    client = FakeClient(canned if canned is not None else canned_with(), clock=lambda: FAKE_CLOCK)
    return run_engine(stmt, client, default_params(stmt.position_date), clock=lambda: FAKE_CLOCK)


def by_cnpj(doc):
    return {ln["cnpj"]: ln for ln in doc["movement"]["lines"]}


def served(z, level, **extra):
    """A function that rewrites the GERACAO row to a served z and level."""
    def fn(rows):
        for r in rows:
            if r["cnpj"] == GERACAO:
                r.update(z=z, level=level, investigator_trigger=level == "forte", **extra)
        return rows
    return fn


@pytest.fixture(scope="module")
def doc():
    return run()


# ---------------------------------------------------------------------------
# The thresholds: strictly greater, on either side, at exactly 2 and exactly 3.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "z, expected",
    [
        ("0", NORMAL), ("1.9999", NORMAL), ("2", NORMAL), ("2.0", NORMAL), ("-2", NORMAL), ("-2.0", NORMAL),
        ("2.0001", ATENCAO), ("-2.0001", ATENCAO), ("2.9999", ATENCAO), ("3", ATENCAO), ("-3", ATENCAO), ("-3.0", ATENCAO),
        ("3.0001", FORTE), ("-3.0001", FORTE), ("12.5", FORTE),
    ],
)
def test_thresholds_are_strictly_greater_at_exactly_2_and_3(z, expected):
    assert classify_z(Decimal(z)) == expected


def test_a_missing_z_has_no_level():
    assert classify_z(None) is None


@pytest.mark.parametrize(
    "z, level",
    [(2.0, "normal"), (-2.0, "normal"), (3.0, "atencao"), (-3.0, "atencao"), (2.1549, "atencao"), (-3.5911, "forte")],
)
def test_the_engine_keeps_the_served_level_at_the_boundaries(z, level):
    doc = run(canned_with(served(z, level)))
    ln = by_cnpj(doc)[GERACAO]
    assert ln["level"] == level and ln["z"] == z
    assert ln["in_table"] == (level in ("atencao", "forte"))
    assert ln["in_text"] == (level == "forte")
    assert ln["investigator_trigger"] == (level == "forte")


def test_a_level_the_served_z_contradicts_is_not_shown_as_a_finding():
    # z = 2.5 cannot be 'forte', z = 3.5 cannot be 'normal': the line becomes nao_avaliado and says why.
    for z, level in ((2.5, "forte"), (3.5, "normal"), (None, "atencao")):
        doc = run(canned_with(served(z, level)))
        ln = by_cnpj(doc)[GERACAO]
        assert ln["level"] == NOT_EVALUATED and ln["z"] is None
        assert ln["in_table"] is False and ln["in_text"] is False and ln["investigator_trigger"] is False
        assert "não confirma" in ln["reason"]
        assert doc["movement"]["status"] == "partial"
    doc = run(canned_with(served(2.5, "forte")))
    assert GERACAO not in [str(x) for x in doc["movement"]["investigator_trigger_line_nos"]]


def test_a_z_a_rounding_away_from_a_threshold_may_sit_on_either_side():
    # The SQL decides on the unrounded z and serves 4 decimals: 2.0000 can be 'atencao' (2.00004 rounded).
    ln = by_cnpj(run(canned_with(served(2.0, "atencao"))))[GERACAO]
    assert ln["level"] == ATENCAO
    ln = by_cnpj(run(canned_with(served(3.0, "forte"))))[GERACAO]
    assert ln["level"] == FORTE


def test_an_unknown_level_is_not_used():
    doc = run(canned_with(served(2.5, "alerta")))
    ln = by_cnpj(doc)[GERACAO]
    assert ln["level"] == NOT_EVALUATED and "desconhecido" in ln["reason"]


# ---------------------------------------------------------------------------
# What the section carries, with the fixture's six funds.
# ---------------------------------------------------------------------------


def test_the_fixture_has_one_of_each_level_and_three_not_evaluated(doc):
    m = doc["movement"]
    assert m["month"] == "2026-09-01"
    assert m["counts"] == {"funds": 6, "normal": 1, "atencao": 1, "forte": 1, "nao_avaliado": 3}
    lv = by_cnpj(doc)
    assert lv[GERACAO]["level"] == ATENCAO and lv[XP_LIQ]["level"] == FORTE
    assert m["investigator_trigger_line_nos"] == [lv[XP_LIQ]["line_no"]]
    assert m["thresholds"] == {
        "atencao_abs_z": 2.0, "forte_abs_z": 3.0, "strictly_greater": True, "min_peers": 30, "winsorized_percentiles": [1, 99],
    }
    assert m["status"] == "partial" and "3 de 6" in m["reason"]


def test_the_engine_states_number_class_sample_and_month(doc):
    ln = by_cnpj(doc)[XP_LIQ]
    assert ln["class_as_filed"] == "RENDA FIXA LIVRE DURAÇÃO - CRÉDITO LIVRE"
    assert (ln["class"], ln["subclass"]) == ("RENDA FIXA LIVRE DURAÇÃO", "CRÉDITO LIVRE")
    assert ln["n_peers"] == 2243 and ln["min_peers"] == 30 and ln["month"] == "2026-09-01"
    assert ln["own_value_pct"] == -2.9 and ln["class_mean_pct"] == 0.535 and ln["class_sd_pct"] == 0.9566
    assert ln["z"] == -3.5911
    assert ln["sources"][0]["tool"] == "portfolio_movement" and ln["sources"][0]["data_date"] == "2026-09-30"
    assert "previsão" in doc["movement"]["note"] and "recomendação" in doc["movement"]["note"]


def test_a_fund_with_no_class_is_not_evaluated_with_the_reason_and_never_normal(doc):
    ln = by_cnpj(doc)[XP_FIC]
    assert ln["level"] == NOT_EVALUATED and ln["level_label"] == "não avaliado"
    assert ln["class_as_filed"] is None and ln["z"] is None and ln["investigator_trigger"] is False
    assert "fora do Extrato" in ln["reason"]
    # the return it did have is shown, not hidden
    assert ln["own_value_pct"] == 1.073045


def test_funds_that_are_not_fi_say_so(doc):
    reasons = {ln["cnpj"]: ln["reason"] for ln in doc["movement"]["lines"] if ln["level"] == NOT_EVALUATED}
    assert any("(fidc)" in r for r in reasons.values()) and any("(fii)" in r for r in reasons.values())


def test_too_few_peers_is_not_evaluated_with_the_count_and_the_minimum():
    def too_few(rows):
        for r in rows:
            if r["cnpj"] == GERACAO:
                r.update(n_peers=12, own_value_pct=11.0, class_mean_pct=None, class_sd_pct=None, class_p01_pct=None,
                         class_p99_pct=None, z=None, level="nao_avaliado", investigator_trigger=False,
                         reason="apenas 12 fundos da classe AÇÕES - ATIVO - LIVRE têm retorno em 2026-09; mínimo 30 para comparar")
        return rows

    doc = run(canned_with(too_few))
    ln = by_cnpj(doc)[GERACAO]
    assert ln["level"] == NOT_EVALUATED and ln["n_peers"] == 12 and ln["min_peers"] == 30
    assert "apenas 12 fundos" in ln["reason"] and "mínimo 30" in ln["reason"]
    assert ln["in_table"] is False and ln["in_text"] is False
    assert doc["movement"]["counts"]["nao_avaliado"] == 4 and doc["movement"]["counts"]["atencao"] == 0


def test_non_fund_lines_are_listed_not_skipped(doc):
    na = doc["movement"]["not_applicable_lines"]
    assert len(na) == doc["statement"]["n_lines"] - doc["movement"]["counts"]["funds"]
    assert all(x["level"] == NOT_EVALUATED and x["reason"] for x in na)


# ---------------------------------------------------------------------------
# A refusal makes the section unknown, with the verbatim error; the report goes on.
# ---------------------------------------------------------------------------


def test_a_refused_call_makes_the_section_unknown_and_every_fund_not_evaluated():
    canned = canned_with()
    canned["portfolio_movement"] = [{"match": {}, "error": '{"code":"22023","message":"portfolio_movement: refused"}'}]
    doc = run(canned)
    m = doc["movement"]
    assert m["status"] == "unknown" and "falhou" in m["reason"]
    assert m["errors"][0]["tool"] == "portfolio_movement" and "refused" in m["errors"][0]["error"]
    assert {ln["level"] for ln in m["lines"]} == {NOT_EVALUATED}
    assert m["investigator_trigger_line_nos"] == []
    assert doc["section_status"]["movement"]["status"] == "unknown"
    assert doc["fees"]["status"] != "unknown"  # the other sections are untouched


def test_a_cnpj_the_function_did_not_return_is_not_evaluated():
    doc = run(canned_with(lambda rows: [r for r in rows if r["cnpj"] != GERACAO]))
    ln = by_cnpj(doc)[GERACAO]
    assert ln["level"] == NOT_EVALUATED and "não devolveu linha" in ln["reason"]


def test_provenance_records_the_call_with_the_month(doc):
    calls = [p for p in doc["provenance"] if p["tool"] == "portfolio_movement"]
    assert len(calls) == 1 and calls[0]["args"]["p_month"] == "2026-09-01" and calls[0]["row_count"] == 6
    assert doc["engine"]["params"]["movement_month"] == "2026-09-01"


# ---------------------------------------------------------------------------
# Which month is judged by default.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "position, month",
    [("2026-09-30", "2026-09-01"), ("2025-12-31", "2025-12-01"), ("2026-02-28", "2026-02-01"), ("2024-02-29", "2024-02-01"),
     ("2026-09-15", "2026-08-01"), ("2026-01-10", "2025-12-01"), ("2026-09-29", "2026-08-01")],
)
def test_default_month_is_the_position_month_only_for_a_month_end(position, month):
    assert default_movement_month(dt.date.fromisoformat(position)) == dt.date.fromisoformat(month)


# ---------------------------------------------------------------------------
# The documented definition, as a reference the served numbers must agree with.
# ---------------------------------------------------------------------------


def _percentile_cont(sorted_values, q):
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (pos - lo) * (sorted_values[hi] - sorted_values[lo])


def _class_stats(values):
    s = sorted(values)
    p01, p99 = _percentile_cont(s, 0.01), _percentile_cont(s, 0.99)
    w = [min(max(x, p01), p99) for x in values]
    mean = sum(w) / len(w)
    sd = (sum((x - mean) ** 2 for x in w) / (len(w) - 1)) ** 0.5
    return mean, sd, p01, p99


def test_reference_winsorization_clamps_the_extremes_in_the_class_scale_and_not_in_the_fund_value():
    core = [1.0 + (i - 147.5) * 0.005 for i in range(1, 295)]
    extremes = [40.0, 35.0, -40.0, -35.0]
    values = core + extremes
    mean, sd, p01, p99 = _class_stats(values)
    raw_mean = sum(values) / len(values)
    raw_sd = (sum((x - raw_mean) ** 2 for x in values) / (len(values) - 1)) ** 0.5
    assert sd * 2 < raw_sd  # the four extremes would more than double the scale
    assert p01 > -2 and p99 < 2  # both bounds sit inside the core
    z_extreme = (40.0 - mean) / sd  # the fund's own value is NOT clamped
    z_if_clamped = (p99 - mean) / sd
    assert z_extreme > 3 > z_if_clamped

    # and the engine accepts a row built from that reference: the served level agrees with the served z
    def row(rows):
        for r in rows:
            if r["cnpj"] == GERACAO:
                z = round((40.0 - mean) / sd, 4)
                r.update(n_peers=len(values), own_value_pct=40.0, class_mean_pct=round(mean, 6), class_sd_pct=round(sd, 6),
                         class_p01_pct=round(p01, 6), class_p99_pct=round(p99, 6), z=z, level="forte", investigator_trigger=True)
        return rows

    ln = by_cnpj(run(canned_with(row)))[GERACAO]
    assert ln["level"] == FORTE and ln["in_text"] is True and ln["n_peers"] == 298
