"""Offline guards for the paid research-agent evaluation path."""

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
