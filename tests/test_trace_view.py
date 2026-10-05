"""Offline tests of scripts/trace_view.py over traces built by src/portfolio/trace.py (synthetic values only)."""

from __future__ import annotations

import json
from pathlib import Path
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


def test_list_needs_the_cloudflare_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(trace_view, "REPO", tmp_path)  # no .env here
    with pytest.raises(SystemExit, match="CLOUDFLARE_ACCOUNT_ID"):
        trace_view.list_keys(1)


def test_credentials_come_from_the_environment_then_the_dotenv_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nPOSTGRES_URL=postgresql://u:p@h:5432/db?sslmode=require\n"
        "export CLOUDFLARE_ACCOUNT_ID=acc-from-file\n"
        "CLOUDFLARE_API_TOKEN=\"tok-from-file\"\n", encoding="utf-8")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    assert trace_view.cloudflare_credentials(env) == {
        "CLOUDFLARE_ACCOUNT_ID": "acc-from-file", "CLOUDFLARE_API_TOKEN": "tok-from-file"}
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-from-env")  # the environment wins
    assert trace_view.cloudflare_credentials(env)["CLOUDFLARE_API_TOKEN"] == "tok-from-env"
    assert trace_view.cloudflare_credentials(tmp_path / "missing.env") == {
        "CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": "tok-from-env"}


def test_list_reads_its_credentials_from_the_dotenv_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("CLOUDFLARE_ACCOUNT_ID=acc\nCLOUDFLARE_API_TOKEN=tok\n", encoding="utf-8")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(trace_view, "REPO", tmp_path)
    seen = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"success": True, "result": []}).encode()

    def fake_urlopen(req, timeout=0):
        seen.append((req.full_url, req.get_header("Authorization")))
        return _R()

    monkeypatch.setattr(trace_view.urllib.request, "urlopen", fake_urlopen)
    assert trace_view.list_keys(1) == []
    assert "/accounts/acc/r2/buckets/silo-diagnosis-traces/objects" in seen[0][0] and seen[0][1] == "Bearer tok"


DEMO_ENGINE = Path(__file__).resolve().parent / "fixtures" / "portfolio" / "demo_engine_output.json"


def test_exposure_says_where_an_assets_exposure_comes_from():
    text = trace_view.exposure_text(json.loads(DEMO_ENGINE.read_text()), "petr4")
    assert "PETR4 (BRPETRACNPR6): R$ 1.031.894,86 = 16,65% da carteira" in text
    assert "direta       PETROBRAS PN (linha 2): R$ 988.000,00" in text
    assert "via fundo    GERAÇÃO L. PAR FIA (linha 3): R$ 43.894,86; 16,59% do valor do fundo; CDA de 2026-05" in text
    assert "não na data do extrato" in text and "Grupo econômico NÃO avaliado" in text


def test_exposure_for_an_asset_in_one_line_only_says_so():
    text = trace_view.exposure_text(json.loads(DEMO_ENGINE.read_text()), "XXXX99")
    assert text.startswith("XXXX99: no asset held through more than one statement line")


def test_exposure_cli_reads_an_engine_file(capsys):
    assert trace_view.main(["exposure", "PETR4", str(DEMO_ENGINE)]) == 0
    assert "16,65% da carteira" in capsys.readouterr().out


def test_engine_doc_of_a_trace_without_an_artifact_is_refused(tmp_path):
    rec = trace.RunRecord(start_ns=T0, end_ns=T0 + 1_000_000_000, status=422, stage="statement", exc_type="StatementError")
    p = tmp_path / "t.json"
    p.write_text(json.dumps(trace.build_trace(rec)))
    with pytest.raises(SystemExit, match="no engine JSON artifact"):
        trace_view.engine_doc(str(p))
