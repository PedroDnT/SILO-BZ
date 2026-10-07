"""The owner's view of the agents (deploy/cloudflare/src/agents.ts) reads what Python wrote.

The trace is built by src/portfolio/trace.py and the investigation section by the investigator's own code; the
TypeScript reads both, so this runs it with Node's type stripping on real Python output. Skipped when Node is
missing or too old to import a .ts file.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.portfolio import trace

ROOT = Path(__file__).resolve().parent.parent
AGENTS_TS = ROOT / "deploy" / "cloudflare" / "src" / "agents.ts"
INDEX_TS = ROOT / "deploy" / "cloudflare" / "src" / "index.ts"
DEMO = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"
T0 = 1_791_300_000_000_000_000


def _ts(fn: str, payload: object) -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)  # a file, not an argument: the demo engine JSON is large
    try:
        script = f"""
import {{ readFileSync }} from "node:fs";
import * as x from {json.dumps(AGENTS_TS.as_uri())};
const input = JSON.parse(readFileSync({json.dumps(f.name)}, "utf8"));
process.stdout.write(JSON.stringify(x.{fn}(input)));
"""
        run = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
                             capture_output=True, text=True, timeout=60)
    finally:
        Path(f.name).unlink(missing_ok=True)
    if run.returncode != 0:
        pytest.skip(f"this node cannot import a .ts file: {run.stderr.strip()[-200:]}")
    return json.loads(run.stdout)


def _full_trace() -> dict:
    n = SimpleNamespace(status="complete", provider="openai", model="gpt-5.1", cost_usd=0.29, reason_code=None, kept=[1, 2, 3])
    n.calls = [
        {"role": "redator", "model": "gpt-5.1-x", "cost_usd": 0.19, "input_tokens": 21000, "output_tokens": 16534,
         "reasoning_tokens": 12844, "ended_unix_nano": T0 + 400_000_000_000},
        {"role": "revisor", "model": "gpt-5.1-x", "cost_usd": 0.05, "input_tokens": 14000, "output_tokens": 4560,
         "reasoning_tokens": 3829, "ended_unix_nano": T0 + 470_000_000_000},
    ]
    n.removed = [SimpleNamespace(finding_id="f2", section="taxas", text="x", reason="Revisor (LLM): y", whole_finding=True)]
    inv = [
        {"role": "investigator_exa", "cost_usd": 0.026, "ended_unix_nano": T0 + 60_000_000_000},
        {"role": "investigator_exa", "cost_usd": 0.026, "ended_unix_nano": T0 + 90_000_000_000},
        {"role": "investigator_extractor", "model": "gpt-5.1", "cost_usd": 0.07, "input_tokens": 9000,
         "output_tokens": 800, "reasoning_tokens": 200, "ended_unix_nano": T0 + 110_000_000_000},
    ]
    rec = trace.RunRecord(
        start_ns=T0, end_ns=T0 + 476_000_000_000, status=200, stage="pdf", engine_rev="0a9b88417cdc", schema_version="1.14",
        engine_start_ns=T0 + 1_000_000_000, engine_end_ns=T0 + 120_000_000_000,
        report_start_ns=T0 + 120_000_000_000, report_end_ns=T0 + 470_000_000_000,
        engine_doc={"section_status": {"fees": {"status": "partial", "reason_codes": []},
                                       "risks": {"status": "complete", "reason_codes": []}},
                    "statement": {"n_lines": 8}},
        narrative=n, engine_json=b"{}", html=b"<html></html>", investigator_calls=inv)
    return json.loads(json.dumps(trace.build_trace(rec, trace_id="ab" * 16)))


def test_the_timeline_reads_every_span_with_its_times_tokens_and_cost():
    t = _ts("agentTimeline", _full_trace())
    assert t["total_s"] == 476 and t["http"] == 200 and t["revisao_do_motor"] == "0a9b88417cdc" and t["esquema"] == "1.14"
    assert t["etapa_que_falhou"] is None and t["custo_usd"] == pytest.approx(0.29)
    rows = {r["nome"]: r for r in t["linhas"]}
    assert [r["nome"] for r in t["linhas"]] == [
        "invoke_workflow diagnosis", "engine.run", "invoke_agent investigator", "invoke_agent redator", "invoke_agent revisor"]
    eng = rows["engine.run"]
    assert eng["inicio_s"] == 1 and eng["duracao_s"] == 119
    assert eng["notas"][0].startswith("seções: ") and "1 partial" in eng["notas"][0] and "1 complete" in eng["notas"][0]
    assert "8 linhas no extrato" in eng["notas"]
    inv = rows["invoke_agent investigator"]
    assert inv["buscas_exa"] == 2 and inv["tokens_saida"] == 800 and inv["custo_usd"] == pytest.approx(0.122) and inv["duracao_s"] == 109
    red = rows["invoke_agent redator"]
    assert red["inicio_s"] == 120 and red["duracao_s"] == 280 and red["tokens_saida"] == 16534 and red["tokens_raciocinio"] == 12844
    assert red["modelo"] == "gpt-5.1-x" and red["estado"] == "ok" and "3 achados mantidos" in red["notas"]
    rev = rows["invoke_agent revisor"]
    assert rev["inicio_s"] == 400 and rev["duracao_s"] == 70 and rev["removidos"] == [{"secao": "taxas", "regra": "llm_review", "inteiro": True}]


def test_a_failed_run_names_its_stage_and_error_type():
    rec = trace.RunRecord(start_ns=T0, end_ns=T0 + 5_000_000_000, status=500, stage="engine", exc_type="RuntimeError",
                          engine_start_ns=T0 + 1_000_000_000)
    t = _ts("agentTimeline", json.loads(json.dumps(trace.build_trace(rec))))
    assert t["http"] == 500 and t["etapa_que_falhou"] == "engine" and t["tipo_do_erro"] == "RuntimeError"
    assert [r["estado"] for r in t["linhas"]] == ["erro", "erro"]


def test_a_document_that_is_not_a_trace_is_null():
    assert _ts("agentTimeline", {}) is None


def test_the_investigation_view_reads_the_sections_the_investigator_writes():
    from tests import test_portfolio_investigator as T

    sec = T.run(T.investigator(T.FakeHttp(T.fnet_routes())), [T.credit_line()])
    doc = {"investigation": sec, "statement": {"positions": [{"line_no": 11, "linha_extrato": "CRA AGRO EXEMPLO"}]}}
    v = _ts("investigationView", doc)
    assert v["ligado"] is True and v["estado"] == "complete"
    assert v["buscas"] == {"usadas": 2, "limite": 20} and v["custo"]["teto_do_investigador_usd"] == 0.3
    assert v["contagens"]["facts"] == 3 and v["contagens"]["tier_a"] == 2 and v["contagens"]["tier_b"] == 1
    assert v["descartados"] == "1 fatos descartados"
    (g,) = v["gatilhos"]
    assert g["linha"] == 11 and g["nome_da_linha"] == "CRA AGRO EXEMPLO" and g["buscas"] == 2 and "isin" in g["identificadores"]
    assert sorted((f["campo"], f["nivel"]) for f in v["fatos"]) == sorted((f["field_label"], f["tier"]) for f in sec["facts"])
    venc = next(f for f in v["fatos"] if f["nivel"] == "A" and f["campo"] == "vencimento")
    assert venc["confere"] == "confere com o registro do SILO" and venc["url"].endswith("downloadDocumento?id=1001")
    assert venc["nivel_rotulo"] == "verificado na fonte" and venc["fonte"] == "Fundos.NET"
    assert v["documentos"][0]["estado"] == "lido" and v["documentos"][0]["cache"] == "miss"


def test_a_run_with_the_investigator_off_says_so():
    v = _ts("investigationView", json.loads(DEMO.read_text()))
    assert v["ligado"] is False and v["estado"] == "not_applicable" and "desligado" in v["motivo"]
    assert v["fatos"] == [] and v["gatilhos"] == []
    assert _ts("investigationView", {"statement": {}}) is None


def test_the_new_routes_sit_behind_the_owner_check_and_the_html_is_stored_by_its_hash():
    src = INDEX_TS.read_text(encoding="utf-8")
    block = src[src.index('pathname.startsWith("/api/traces") && request.method === "GET"'):]
    block = block[:block.index("return erro(404")] if "return erro(404" in block else block[:2500]
    for route in ("/api/traces/report", "/api/traces/agents", "/api/traces/investigation"):
        assert f'pathname === "{route}"' in block
    assert "await ownerOnly" in block.split('pathname === "/api/traces/report"')[0]  # the check comes first
    assert r"const SHA256_KEY = /^artifacts\/[0-9a-f]{64}\.(json|html)$/;" in src
    assert 'artifacts/${await sha256Hex(body)}.${ext}' in src  # a body must hash to its own key, whatever the extension


def test_the_report_frame_runs_no_script_and_the_report_policy_forbids_requests():
    src = INDEX_TS.read_text(encoding="utf-8")
    page = src[src.index("const TRACES_PAGE"):]
    frame = re.search(r'<iframe id="report"[^>]*>', page).group(0)
    assert 'sandbox="allow-same-origin allow-modals"' in frame and "allow-scripts" not in frame
    served = src[src.index("async function traceReport"):src.index("async function traceAgents")]
    assert "default-src 'none'" in served and "sandbox" in served and "script-src" not in served
