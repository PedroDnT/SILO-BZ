"""Offline guards for the paid research-agent evaluation path."""

import json
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from research_examples import agent_eval


def test_twelve_private_cases_fit_the_authorized_spend_cap():
    cases = agent_eval.load_cases()
    assert len(cases) == 12
    assert {case["expected_disposition"] for case in cases} == {
        "answer_or_bounded_limit", "limitation"
    }
    assert len(cases) * agent_eval.worst_case_cost_usd() <= 20


def test_discovery_check_rejects_failed_or_late_catalog_calls():
    valid = [
        {"name": "silo_catalog", "arguments": {}},
        {"name": "silo_tools", "arguments": {"query": ""}},
        {"name": "silo_call", "arguments": {"endpoint": "coverage"}},
        {"name": "silo_call", "arguments": {"endpoint": "inflation"}},
    ]
    assert agent_eval.process_checks(valid, "answer_or_bounded_limit")["discovery_before_data"]

    failed_catalog = [{**valid[0], "error_type": "SiloTimeout"}, *valid[1:]]
    assert not agent_eval.process_checks(failed_catalog, "answer_or_bounded_limit")["discovery_before_data"]
    assert not agent_eval.process_checks([valid[2], valid[0], valid[1]], "answer_or_bounded_limit")["discovery_before_data"]


def test_summary_keeps_evaluator_review_notes_out_of_agent_answer():
    record = {
        "started_at": "2026-09-23T00:00:00Z", "model": "gpt-5-mini",
        "budget_usd": 20.0, "estimated_usd": 0.01, "run_note": "",
        "cases": [{
            "id": "Q1", "question": "A professional question?", "status": "completed",
            "duration_seconds": 1.5, "estimated_usd": 0.01, "answer": "Limited answer.",
            "checks": {"discovery_before_data": True, "data_calls": 1,
                       "catalog_discovered": True, "tools_inspected": True,
                       "coverage_attempted": True},
        }],
    }
    summary = agent_eval._summary_md(record)
    assert "Limited answer." in summary
    assert "Discovery before data" in summary
    assert "OPENAI_API_KEY" not in summary


def test_empty_inherited_key_uses_ignored_local_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=synthetic-test-value\n")
    monkeypatch.setattr(agent_eval, "ROOT", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert agent_eval.load_local_openai_key()
    assert agent_eval.os.environ["OPENAI_API_KEY"] == "synthetic-test-value"


def test_published_schema_discovery_exposes_sdk_names_types_and_requiredness():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    args = agent_eval.endpoint_arguments(contract, "focus_expectations")
    by_name = {item["name"]: item for item in args}
    assert by_name["endpoint"]["required"] is True
    assert by_name["horizon"]["required"] is True
    assert by_name["start"]["required"] is False
    assert by_name["start"]["format"] == "date"
    assert "p_endpoint" not in by_name


def test_invalid_arguments_fail_before_network_call():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())

    class NoNetwork:
        def focus_expectations(self, **kwargs):
            raise AssertionError("network call should not happen")

    adapter = agent_eval.SiloTools(NoNetwork(), contract)
    adapter.catalog_seen = adapter.tools_seen = True
    with pytest.raises(agent_eval.ArgumentValidationError, match="Missing required.*horizon"):
        adapter.invoke_endpoint("focus_expectations", '{"endpoint":"ExpectativasMercadoAnuais"}')
    with pytest.raises(agent_eval.ArgumentValidationError, match="Unknown argument.*p_endpoint"):
        adapter.invoke_endpoint("focus_expectations", '{"p_endpoint":"x","horizon":"2025"}')
    with pytest.raises(agent_eval.ArgumentValidationError, match="ISO date"):
        adapter.invoke_endpoint("focus_expectations", '{"endpoint":"x","horizon":"2025","start":"yesterday"}')
    assert adapter.data_calls == 0


def test_valid_schema_arguments_reach_sdk_and_are_auditable():
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    observed = []

    class FakeClient:
        def focus_expectations(self, endpoint, horizon, indicator=None, start=None, end=None):
            observed.append((endpoint, horizon, indicator, start, end))
            return [{"survey_date": "2024-12-06", "median": 4.59}]

    adapter = agent_eval.SiloTools(FakeClient(), contract)
    adapter.catalog_seen = adapter.tools_seen = True
    result = adapter._record("silo_call", {"endpoint": "focus_expectations"}, lambda: adapter.invoke_endpoint(
        "focus_expectations", '{"endpoint":"ExpectativasMercadoAnuais","horizon":"2025","indicator":"IPCA","start":"2024-12-06"}'))
    assert json.loads(result)[0]["median"] == 4.59
    assert observed == [("ExpectativasMercadoAnuais", "2025", "IPCA", "2024-12-06", None)]
    assert adapter.events[0]["result_json"] == result
    assert len(adapter.events[0]["result_sha256"]) == 64


def test_safe_api_error_retains_code_and_message_without_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-token")
    error = agent_eval.SiloError(404, json.dumps({
        "code": "PGRST202", "message": "function unavailable synthetic-secret-token"
    }), "https://example.invalid/rpc/focus_expectations")
    safe = agent_eval.safe_tool_error(error)
    assert safe["status"] == 404
    assert safe["code"] == "PGRST202"
    assert "function unavailable" in safe["message"]
    assert "synthetic-secret-token" not in json.dumps(safe)
    assert "example.invalid" not in json.dumps(safe)


def test_runtime_input_is_only_the_professional_question():
    case = {"question": "What changed?", "review": "private answer", "expected_disposition": "limitation"}
    assert agent_eval.runtime_question(case) == "What changed?"


def test_private_references_cover_every_case_and_question_has_no_endpoint_hint():
    cases = agent_eval.load_cases()
    reference = json.loads((agent_eval.ROOT / "research_examples/eval_reference.json").read_text())
    contract = json.loads((agent_eval.ROOT / "openapi.json").read_text())
    assert set(reference["cases"]) == {case["id"] for case in cases}
    for case in cases:
        assert all(reference["cases"][case["id"]].get(key) for key in
                   ("contract_endpoints", "identifier", "date_rule", "valid_join", "calculation", "required_caveat", "deterministic_check"))
        assert all(f"/rpc/{endpoint}" in contract["paths"] for endpoint in reference["cases"][case["id"]]["contract_endpoints"])
        assert "/rpc/" not in case["question"]


def test_technical_failure_and_full_rubric_pass_are_separate():
    item = {"status": "completed", "tool_events": [{"error": {"code": "PGRST202"}}]}
    assert agent_eval.technical_classification(item) == "api_unavailable"
    checks = dict.fromkeys(("disposition", "identifiers_and_periods", "calculation_or_limitation",
                            "source_citation", "material_caveats"), True)
    assert agent_eval.full_rubric_pass(item, checks)
    assert not agent_eval.full_rubric_pass(item, {**checks, "hard_failures": ["invented_join"]})
    assert not agent_eval.full_rubric_pass(item, {**checks, "source_citation": False})
    assert not agent_eval.full_rubric_pass({"status": "error"}, checks)
    assert agent_eval.technical_classification({"status": "error", "error_type": "MaxTurnsExceeded"}) == "turn_exhaustion"


def test_baseline_review_is_complete_and_does_not_confuse_completion_with_pass():
    run = json.loads((agent_eval.ROOT / "research_examples/eval-results.json").read_text())
    review = json.loads((agent_eval.ROOT / "research_examples/baseline-review.json").read_text())
    assert review["run_started_at"] == run["started_at"]
    assert set(review["cases"]) == {case["id"] for case in run["cases"]}
    passed = [case["id"] for case in run["cases"] if agent_eval.full_rubric_pass(case, review["cases"][case["id"]])]
    assert passed == ["L1", "L3"]
    assert sum(case["status"] == "completed" for case in run["cases"]) == 11
    assert Decimal("56508.93") * Decimal("0.124") == Decimal("7007.10732")
    assert Decimal("4.59") - Decimal("4.26") == Decimal("0.33")


def test_paid_run_requires_fresh_matching_passed_live_preflight(tmp_path):
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "preflight.json"
    report = {
        "checked_at": "2026-09-25T11:00:00Z", "base_url": "https://example.invalid",
        "read_only": True, "status": "passed",
        "endpoints": {name: {"status": "passed"} for name in agent_eval.REQUIRED_RESEARCH_RPCS},
    }
    path.write_text(json.dumps(report))
    agent_eval.validate_preflight_report(path, "https://example.invalid", now)
    report["endpoints"]["focus_expectations"]["status"] = "PGRST202"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="all three"):
        agent_eval.validate_preflight_report(path, "https://example.invalid", now)
    report["endpoints"]["focus_expectations"]["status"] = "passed"
    report["checked_at"] = "2026-09-24T00:00:00Z"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="six hours"):
        agent_eval.validate_preflight_report(path, "https://example.invalid", now)
