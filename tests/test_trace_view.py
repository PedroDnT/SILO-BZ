"""Offline tests of scripts/trace_view.py over traces built by src/portfolio/trace.py (synthetic values only)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import trace_view
from src.portfolio import trace

T0 = 1_791_300_000_000_000_000  # 2026-10-06 15:20:00 UTC


def _complete() -> dict:
    n = SimpleNamespace(status="complete", provider="openai", model="gpt-5.1", cost_usd=0.21, reason_code=None,
                        kept=[1, 2, 3])
    n.calls = [
        {"role": "redator", "model": "gpt-5.1-x", "cost_usd": 0.15, "input_tokens": 9000, "output_tokens": 4000,
         "reasoning_tokens": 3000, "ended_unix_nano": T0 + 30_000_000_000},
        {"role": "revisor", "model": "gpt-5.1-x", "cost_usd": 0.06, "input_tokens": 7000, "output_tokens": 500,
         "ended_unix_nano": T0 + 40_000_000_000},
    ]
    n.removed = [SimpleNamespace(finding_id="f2", section="taxas", text="x", reason="Revisor (LLM): y", whole_finding=True)]
    rec = trace.RunRecord(start_ns=T0, end_ns=T0 + 42_000_000_000, status=200, stage="pdf", files=1, formats="xlsx",
                          in_bytes=123, engine_rev="abc123", schema_version="1.11",
                          engine_start_ns=T0 + 100_000_000, engine_end_ns=T0 + 3_000_000_000,
                          report_start_ns=T0 + 3_000_000_000, report_end_ns=T0 + 41_000_000_000,
                          engine_doc={"section_status": {"fees": {"status": "partial", "reason_codes": ["sem_taxa"]}},
                                      "identification": {"counts": {"identified": 7, "unknown": 1}}},
                          narrative=n, engine_json=b'{"a":1}', pdf=b"%PDF-1.7 x")
    return json.loads(json.dumps(trace.build_trace(rec, trace_id="ab" * 16)))


def test_a_complete_trace_reads_as_a_timeline():
    text = trace_view.render(_complete())
    assert "Trace " + "ab" * 16 in text and "HTTP 200 OK" in text and "42.0s" in text
    assert "2026-10-06 12:20:00 UTC-3 (15:20:00 UTC)" in text
    sha = trace.sha256_hex(b'{"a":1}')
    assert f"artifacts/{sha}.json (7 B)" in text
    assert "├ engine.run" in text and "└ invoke_agent revisor" in text
    assert "fees" in text and "partial" in text and "sem_taxa" in text
    assert "identified 7 · unknown 1" in text
    assert "gpt-5.1 (answered by gpt-5.1-x)" in text and "tokens in 9000 out 4000 reasoning 3000" in text
    assert "narrative complete" in text and "findings kept 3" in text and "removed 1" in text
    assert "llm_review" in text and "taxas" in text and "whole" in text


def test_a_failed_trace_names_its_stage_and_error_type():
    rec = trace.RunRecord(start_ns=T0, end_ns=T0 + 5_000_000_000, status=500, stage="engine", exc_type="RuntimeError",
                          engine_start_ns=T0 + 1_000_000_000)
    text = trace_view.render(json.loads(json.dumps(trace.build_trace(rec))))
    assert "HTTP 500 ERROR" in text and "FAILED at stage engine: RuntimeError" in text
    assert "Engine error: RuntimeError" in text and "Agents" not in text


def test_several_traces_read_as_one_row_each():
    row = trace_view.row(_complete())
    assert row.startswith("2026-10-06 12:20:00 UTC-3") and "abababababab" in row
    assert "200" in row and "tokens   20500" in row and "removed  1" in row and "schema 1.11" in row


def test_show_reads_local_files(tmp_path, capsys):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_complete()))
    assert trace_view.main(["show", str(p), str(p)]) == 0
    assert capsys.readouterr().out.count("abababababab") == 2


def test_listing_parse_and_refusal():
    ok = {"success": True, "result": [{"key": "traces/2026/10/06/x.json", "size": 10}]}
    assert trace_view.parse_listing(ok)[0]["key"] == "traces/2026/10/06/x.json"
    with pytest.raises(SystemExit, match="10000"):
        trace_view.parse_listing({"success": False, "errors": [{"code": 10000}]})


def test_list_needs_the_cloudflare_env(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="CLOUDFLARE_ACCOUNT_ID"):
        trace_view.list_keys(1)
