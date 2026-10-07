"""Offline tests of the one diagnosis entry point (src/portfolio/diagnosis.py).

SILO is the FakeClient over the canned rows and the LLM the fake provider, as in
test_portfolio_server.py, which keeps only the HTTP mapping of these results.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.portfolio import diagnosis, trace
from src.portfolio.client import FakeClient, load_fake_rows
from src.portfolio.common import SiloUnavailable
from src.portfolio.statement import read_statement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"


def _client():
    return FakeClient(load_fake_rows(FAKE_ROWS))


def _stub_pdf(html_text, out_path):
    assert "<html" in html_text.lower()
    Path(out_path).write_bytes(b"%PDF-1.7\n% stub\n")
    return Path(out_path)


@pytest.fixture()
def stmt():
    return read_statement(TEMPLATE)


def test_diagnose_runs_engine_and_report_and_fills_the_record(stmt, monkeypatch):
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    res = diagnosis.diagnose(stmt, _client)
    assert res.pdf is None  # no renderer: HTML only
    assert res.engine == json.loads(res.engine_json)
    assert res.engine["statement"]["holder"] == {"titular": "[TITULAR]", "cpf": "[CPF]", "conta": "[CONTA]"}
    assert "Resumo para a reuni" in res.html
    assert res.narrative.provider == "fake" and res.narrative.cost_usd == 0
    rec = res.record
    assert rec.stage == "report"
    assert rec.engine_json == res.engine_json.encode("utf-8") and rec.html == res.html.encode("utf-8")
    assert rec.narrative is res.narrative and rec.pdf is None
    assert rec.engine_doc == diagnosis.trace_summary(res.engine)
    assert rec.engine_start_ns <= rec.engine_end_ns <= rec.report_start_ns <= rec.report_end_ns
    assert rec.documents == {} and rec.investigator_calls == []
    assert res.engine_s >= 0 and res.report_s >= 0


def test_the_report_half_is_what_the_cli_writes_from_the_same_engine_json(stmt):
    res = diagnosis.diagnose(stmt, _client, provider_name="fake")
    again = diagnosis.render_report(json.loads(res.engine_json), "fake")
    assert again.view == res.view
    assert again.html == res.html


def test_a_pdf_renderer_adds_the_pdf_to_the_result_and_the_record(stmt, tmp_path):
    rec = trace.RunRecord(start_ns=0, end_ns=0, status=500, stage="read")
    res = diagnosis.diagnose(stmt, _client, provider_name="fake", pdf_renderer=_stub_pdf, workdir=tmp_path, record=rec)
    assert res.record is rec and rec.stage == "pdf"
    assert res.pdf.startswith(b"%PDF") and rec.pdf == res.pdf


def test_a_pdf_needs_a_workdir(stmt):
    with pytest.raises(ValueError):
        diagnosis.diagnose(stmt, _client, provider_name="fake", pdf_renderer=_stub_pdf)


def test_constraints_are_refused_before_silo_is_read(stmt):
    def forbidden():
        raise AssertionError("invalid input must not reach SILO")

    for bad in ({"horizon_date": "2000-01-01"}, {"profile": "temerario"}, {"other": 1}, ["not", "a", "dict"]):
        with pytest.raises(diagnosis.InvalidConstraints):
            diagnosis.diagnose(stmt, forbidden, constraints=bad, provider_name="fake")


def test_valid_constraints_reach_the_engine(stmt):
    c = {"profile": "conservador", "horizon_date": "2027-01-01", "liquidity_brl": "1000", "liquidity_date": "2027-01-01"}
    res = diagnosis.diagnose(stmt, _client, constraints=c, provider_name="fake")
    assert "conservador" in res.html and "suitability" in res.html


def test_constraints_are_validated_once_per_run(stmt, monkeypatch):
    from src.portfolio import client_fit
    calls = []
    real = client_fit.validate_input

    def counting(raw, position_date):
        calls.append(raw)
        return real(raw, position_date)

    monkeypatch.setattr(client_fit, "validate_input", counting)
    c = {"profile": "conservador", "horizon_date": "2027-01-01", "liquidity_brl": "1000", "liquidity_date": "2027-01-01"}
    res = diagnosis.diagnose(stmt, _client, constraints=c, provider_name="fake")
    assert calls == [c]
    assert res.engine["client_fit"]["declared"] == real(c, stmt.position_date)


def test_the_engine_takes_only_validated_constraints(stmt):
    from src.portfolio import client_fit
    from src.portfolio.engine import run_engine

    with pytest.raises(TypeError):  # raw input that skipped the entry point's validation
        run_engine(stmt, _client(), client_constraints={"profile": "conservador"})
    earlier = stmt.position_date.replace(year=stmt.position_date.year - 1)
    other = client_fit.declare({"profile": "conservador"}, earlier)
    with pytest.raises(ValueError):  # validated against another statement date
        run_engine(stmt, _client(), client_constraints=other)


def test_an_llm_failure_is_report_failed_with_the_type_name_only(stmt, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rec = trace.RunRecord(start_ns=0, end_ns=0, status=500, stage="read")
    with pytest.raises(diagnosis.ReportFailed) as exc:
        diagnosis.diagnose(stmt, _client, provider_name="anthropic", record=rec)
    assert exc.value.exc_type and str(exc.value) == exc.value.exc_type
    assert rec.stage == "report" and rec.engine_json  # the engine half is on the record


def test_silo_unavailable_propagates_at_the_engine_stage(stmt):
    def down():
        raise SiloUnavailable("timeout")

    rec = trace.RunRecord(start_ns=0, end_ns=0, status=500, stage="read")
    with pytest.raises(SiloUnavailable):
        diagnosis.diagnose(stmt, down, provider_name="fake", record=rec)
    assert rec.stage == "engine"


def test_the_investigator_books_on_the_reports_one_meter(stmt):
    seen = {}

    def factory(meter):
        seen["meter"] = meter
        meter.book("investigator_extractor", "gpt-5.1", 0.2, input_tokens=1, output_tokens=1)
        return None  # off: the engine runs without one

    res = diagnosis.diagnose(stmt, _client, investigator_factory=factory, provider_name="fake")
    assert [c["role"] for c in res.record.investigator_calls] == ["investigator_extractor"]
    assert res.narrative.cost_usd == pytest.approx(0.2)


def test_read_uploads_reads_the_template_and_refuses_garbage_by_type_name(tmp_path):
    st = diagnosis.read_uploads([(TEMPLATE.read_bytes(), "xlsx")], tmp_path)
    assert st.positions and list(tmp_path.iterdir()) == []  # the xlsx copy is removed at once
    with pytest.raises(diagnosis.UnreadableStatement) as exc:
        diagnosis.read_uploads([(b"PK\x03\x04 MARIA FICTICIA not a zip", "xlsx")], tmp_path)
    assert "MARIA" not in str(exc.value) and exc.value.exc_type


# --- the narrative (report/build.py) --------------------------------------------------------------------------------


def test_revisor_removing_everything_is_a_fixed_reason_code(monkeypatch):
    from src.portfolio.report import build, revisor
    from src.portfolio.report.redator import RedatorResult

    one = build.redator.Finding("f1", "resumo", "t", "x", ["p1"])
    monkeypatch.setattr(build.redator, "write", lambda engine, provider: RedatorResult("complete", [one]))
    monkeypatch.setattr(revisor, "check", lambda engine, findings: revisor.RevisorResult(kept=[], removed=[], notes=[]))
    n = build.make_narrative({}, SimpleNamespace(name="fake", model="fake", meter=build.llm.CostMeter()), llm_review=False)
    assert n.status == "unknown" and n.reason_code == "revisor_removed_all"


def test_zero_findings_drafted_is_a_complete_narrative(monkeypatch):
    # engine 1.7: a portfolio with nothing to point out is a valid answer, not a failed narrative
    from src.portfolio.report import build, revisor
    from src.portfolio.report.redator import RedatorResult

    monkeypatch.setattr(build.redator, "write", lambda engine, provider: RedatorResult("complete", []))
    monkeypatch.setattr(revisor, "check", lambda engine, findings: revisor.RevisorResult(kept=[], removed=[], notes=[]))
    n = build.make_narrative({}, SimpleNamespace(name="fake", model="fake", meter=build.llm.CostMeter()), llm_review=False)
    assert n.status == "complete" and n.reason_code is None and n.kept == []
