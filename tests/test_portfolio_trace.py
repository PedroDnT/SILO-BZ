"""Offline tests of the run trace (src/portfolio/trace.py) and its two server paths (ADR 0003).

The statement is the synthetic template (fictitious holder); SILO is the FakeClient over
the canned rows and the LLM the fake provider, as in test_portfolio_server.py.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("pydantic")

from src.portfolio import server, trace  # noqa: E402
from src.portfolio.common import SiloUnavailable  # noqa: E402
from src.portfolio.report.render import Narrative  # noqa: E402
from src.portfolio.report.revisor import Removal  # noqa: E402
from tests.test_portfolio_server import PRIVATE, TEMPLATE, TOKEN, UPLOAD_NAME, _auth, _client, _stub_pdf  # noqa: E402

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    return server.create_app(client_factory=_client).test_client()


def _spans(otlp: dict) -> list[dict]:
    rs = otlp["resourceSpans"]
    assert len(rs) == 1
    ss = rs[0]["scopeSpans"]
    assert len(ss) == 1 and ss[0]["scope"]["name"] == trace.SCOPE_NAME
    return ss[0]["spans"]


def _attrs(span: dict) -> dict:
    return {kv["key"]: next(iter(kv["value"].values())) for kv in span["attributes"]}


def assert_valid_otlp(otlp: dict) -> list[dict]:
    spans = _spans(otlp)
    tid = spans[0]["traceId"]
    assert HEX32.match(tid)
    ids = {s["spanId"] for s in spans}
    assert len(ids) == len(spans)
    root = spans[0]
    assert "parentSpanId" not in root and root["name"] == "invoke_workflow diagnosis"
    for s in spans:
        assert s["traceId"] == tid and HEX16.match(s["spanId"])
        if s is not root:
            assert s["parentSpanId"] == root["spanId"]
        assert isinstance(s["startTimeUnixNano"], str) and isinstance(s["endTimeUnixNano"], str)
        assert int(s["endTimeUnixNano"]) >= int(s["startTimeUnixNano"]) > 0
        assert s["kind"] == trace.SPAN_KIND_INTERNAL and s["status"]["code"] in (0, 1, 2)
        for kv in s["attributes"]:
            assert set(kv) == {"key", "value"} and len(kv["value"]) == 1
            (kind, v), = kv["value"].items()
            assert kind in ("stringValue", "intValue", "doubleValue", "boolValue", "arrayValue")
            if kind == "intValue":
                assert isinstance(v, str) and int(v) == int(v)
        for ev in s.get("events", []):
            assert isinstance(ev["timeUnixNano"], str) and ev["name"]
    return spans


# --- trace.py, pure ---------------------------------------------------------------------------------------------------


def test_removal_reasons_become_fixed_codes_never_text():
    assert trace.removal_code("algarismo fora de marcador") == ("digit_outside_placeholder", "text")
    assert trace.removal_code("título: sem citação de proveniência") == ("no_citation", "title")
    assert trace.removal_code("Revisor (LLM): MARIA FICTÍCIA tem demais") == ("llm_review", "text")
    assert trace.removal_code("valor extremo (max) sem segundo caminho que o confirme: {{x}}")[0] == "extreme_value_unconfirmed"
    assert trace.removal_code("anything else MARIA") == ("other", "text")


def test_a_complete_run_builds_valid_otlp_with_agents_and_revisor_events():
    n = Narrative(status="complete", provider="openai", model="gpt-5.1", cost_usd=0.21)
    n.calls = [
        {"role": "redator", "model": "gpt-5.1-x", "cost_usd": 0.15, "input_tokens": 9000, "output_tokens": 4000,
         "reasoning_tokens": 3000, "ended_unix_nano": 1_500},
        {"role": "revisor", "model": "gpt-5.1-x", "cost_usd": 0.06, "input_tokens": 7000, "output_tokens": 500,
         "ended_unix_nano": 1_800},
    ]
    secret = "MARIA FICTÍCIA tem R$ 5.651.424"
    n.removed = [Removal("f2", "taxas", "t", secret, "Revisor (LLM): " + secret, True),
                 Removal("f3", "risco", "t", "x 1", "algarismo fora de marcador", False)]
    engine = {"section_status": {"fees": {"status": "partial", "reason": "MARIA free text", "reason_codes": ["sem_taxa"]}},
              "identification": {"counts": {"identified": 7, "unknown": 1}}}
    rec = trace.RunRecord(start_ns=1_000, end_ns=2_000, status=200, stage="pdf", files=1, formats="xlsx",
                          in_bytes=123, engine_rev="abc123def456", schema_version="1.9",
                          engine_start_ns=1_100, engine_end_ns=1_200, report_start_ns=1_200, report_end_ns=1_900,
                          engine_doc=engine, narrative=n, engine_json=b'{"a":1}', pdf=b"%PDF-1.7 x")
    otlp = trace.build_trace(rec)
    spans = assert_valid_otlp(otlp)
    assert [s["name"] for s in spans] == ["invoke_workflow diagnosis", "engine.run", "invoke_agent redator", "invoke_agent revisor"]
    root = _attrs(spans[0])
    assert root["app.http.status"] == "200" and "app.failed_stage" not in root
    assert root["app.engine.schema_version"] == "1.9" and root["app.engine.rev"] == "abc123def456"
    assert root["app.semconv"] == trace.GENAI_SEMCONV and "app.git_sha" not in root
    assert root["app.pdf.sha256"] == trace.sha256_hex(b"%PDF-1.7 x")
    assert root["app.engine_json.sha256"] == trace.sha256_hex(b'{"a":1}')
    assert spans[0]["status"]["code"] == trace.STATUS_OK
    eng = _attrs(spans[1])
    assert eng["app.section.fees.status"] == "partial"
    assert eng["app.section.fees.reason_codes"] == {"values": [{"stringValue": "sem_taxa"}]}
    assert eng["app.identification.identified"] == "7"
    red, rev = _attrs(spans[2]), _attrs(spans[3])
    assert red["gen_ai.provider.name"] == "openai" and red["gen_ai.request.model"] == "gpt-5.1"
    assert red["gen_ai.usage.input_tokens"] == "9000" and red["gen_ai.usage.output_tokens"] == "4000"
    assert rev["gen_ai.usage.input_tokens"] == "7000" and rev["app.findings.removed"] == "2"
    assert spans[2]["endTimeUnixNano"] == "1500" and spans[3]["startTimeUnixNano"] == "1500"
    events = spans[3]["events"]
    assert [e["name"] for e in events] == ["app.revisor.removed"] * 2
    ev = {kv["key"]: next(iter(kv["value"].values())) for kv in events[0]["attributes"]}
    assert ev["app.revisor.rule"] == "llm_review" and ev["app.finding.section"] == "taxas"
    assert ev["app.finding.text_sha256"] == trace.sha256_hex(secret.encode())
    text = json.dumps(otlp, ensure_ascii=False)
    assert "MARIA" not in text and "5.651.424" not in text


def test_a_failed_run_is_an_error_with_the_type_only():
    rec = trace.RunRecord(start_ns=10, end_ns=20, status=500, stage="engine", exc_type="RuntimeError",
                          engine_start_ns=12)
    spans = assert_valid_otlp(trace.build_trace(rec))
    assert spans[0]["status"]["code"] == trace.STATUS_ERROR
    assert _attrs(spans[0])["app.failed_stage"] == "engine"
    assert spans[0]["events"][0]["name"] == "exception"
    assert spans[0]["events"][0]["attributes"] == [{"key": "exception.type", "value": {"stringValue": "RuntimeError"}}]
    assert spans[1]["name"] == "engine.run" and spans[1]["status"]["code"] == trace.STATUS_ERROR


def test_artifacts_are_named_by_their_sha256():
    arts = trace.artifact_objects(b"{}", b"%PDF")
    assert arts == {f"artifacts/{trace.sha256_hex(b'{}')}.json": b"{}", f"artifacts/{trace.sha256_hex(b'%PDF')}.pdf": b"%PDF"}
    assert trace.artifact_objects(None, None) == {}
    both = trace.artifact_objects(b"{}", None, b"<html></html>")
    assert both == {f"artifacts/{trace.sha256_hex(b'{}')}.json": b"{}",
                    f"artifacts/{trace.sha256_hex(b'<html></html>')}.html": b"<html></html>"}


def test_the_root_span_names_the_html_it_kept():
    rec = trace.RunRecord(start_ns=1, end_ns=2, status=200, stage="pdf", html=b"<html>x</html>")
    root = trace.root_attributes(trace.build_trace(rec))
    assert root["app.html.sha256"] == trace.sha256_hex(b"<html>x</html>") and root["app.html.bytes"] == "14"
    bare = trace.root_attributes(trace.build_trace(trace.RunRecord(start_ns=1, end_ns=2, status=500, stage="engine")))
    assert "app.html.sha256" not in bare


# --- the server -------------------------------------------------------------------------------------------------------


def _fetch(app, tid, headers=None):
    return app.get(f"/trace/{tid}", headers=_auth() if headers is None else headers)


def test_a_200_run_names_its_trace_and_serves_it_once_with_the_masked_engine_json(app, monkeypatch):
    _stub_pdf(monkeypatch)
    upload = TEMPLATE.read_bytes()
    r = app.post("/diagnose", data={"file": (io.BytesIO(upload), UPLOAD_NAME)},
                 content_type="multipart/form-data", headers=_auth())
    assert r.status_code == 200
    tid = r.headers[server.TRACE_HEADER]
    assert HEX32.match(tid)

    assert _fetch(app, tid, {}).status_code == 401
    assert _fetch(app, tid, _auth("wrong")).status_code == 401
    got = _fetch(app, tid)
    assert got.status_code == 200 and got.headers["Cache-Control"] == "no-store"
    assert _fetch(app, tid).status_code == 404  # read once, then forgotten
    assert _fetch(app, "0" * 32).status_code == 404
    assert _fetch(app, "not-an-id").status_code == 404

    bundle = got.json
    assert bundle["trace_id"] == tid
    spans = assert_valid_otlp(bundle["trace"])
    assert spans[0]["traceId"] == tid
    root = _attrs(spans[0])
    assert root["app.http.status"] == "200" and root["app.formats"] == "xlsx"
    assert root["app.in_bytes"] == str(len(upload)) and root["app.files"] == "1"
    assert root["app.pdf.sha256"] == trace.sha256_hex(r.data)
    assert [s["name"] for s in spans][:3] == ["invoke_workflow diagnosis", "engine.run", "invoke_agent redator"]
    assert _attrs(spans[2])["gen_ai.provider.name"] == "fake"

    arts = {k: base64.b64decode(v) for k, v in bundle["artifacts"].items()}
    (key,), = [[k for k in arts if k.endswith(".json")]]
    engine_bytes = arts[key]
    assert key == f"artifacts/{root['app.engine_json.sha256']}.json" == f"artifacts/{trace.sha256_hex(engine_bytes)}.json"
    # the report's HTML is kept beside it, whatever the output format, and hashes to the root span's attribute
    (hkey,), = [[k for k in arts if k.endswith(".html")]]
    html_bytes = arts[hkey]
    assert hkey == f"artifacts/{root['app.html.sha256']}.html" == f"artifacts/{trace.sha256_hex(html_bytes)}.html"
    assert html_bytes.startswith(b"<!") or b"<html" in html_bytes[:200].lower()
    assert set(arts) == {key, hkey}
    engine = json.loads(engine_bytes)
    assert engine["statement"]["holder"] == {"titular": "[TITULAR]", "cpf": "[CPF]", "conta": "[CONTA]"}

    raw = got.data
    assert upload not in raw and upload[:64] not in engine_bytes
    assert base64.b64encode(upload)[:64] not in raw
    text = raw.decode("utf-8") + engine_bytes.decode("utf-8") + html_bytes.decode("utf-8")
    for s in PRIVATE:
        assert s not in text, f"{s!r} reached the trace"


def test_an_html_run_keeps_its_report_in_the_trace_too(app):
    # the upload page asks for output_format=html, so these runs have no PDF: the HTML is what the owner reads later
    r = app.post("/diagnose", data={"file": (io.BytesIO(TEMPLATE.read_bytes()), UPLOAD_NAME), "output_format": "html"},
                 content_type="multipart/form-data", headers=_auth())
    assert r.status_code == 200 and r.mimetype == "text/html"
    bundle = _fetch(app, r.headers[server.TRACE_HEADER]).json
    root = _attrs(assert_valid_otlp(bundle["trace"])[0])
    assert "app.pdf.sha256" not in root
    arts = {k: base64.b64decode(v) for k, v in bundle["artifacts"].items()}
    assert arts[f"artifacts/{root['app.html.sha256']}.html"] == r.data  # exactly what the caller received


def test_the_trace_header_never_appears_without_the_token(app):
    r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth("wrong"))
    assert r.status_code == 401 and server.TRACE_HEADER not in r.headers


def test_a_422_run_has_a_trace_with_the_stage_and_no_artifact(app):
    r = app.post("/diagnose", data=b"PK\x03\x04 " + "MARIA FICTÍCIA 123.456.789-09".encode(), headers=_auth())
    assert r.status_code == 422
    bundle = _fetch(app, r.headers[server.TRACE_HEADER]).json
    spans = assert_valid_otlp(bundle["trace"])
    root = _attrs(spans[0])
    assert root["app.failed_stage"] == "read" and root["app.http.status"] == "422"
    assert spans[0]["status"]["code"] == trace.STATUS_ERROR and len(spans) == 1
    assert bundle["artifacts"] == {}
    assert "MARIA" not in json.dumps(bundle, ensure_ascii=False)


def test_a_500_run_records_the_exception_type_never_its_message(monkeypatch):
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)

    def boom():
        raise RuntimeError("MARIA FICTÍCIA 12345-6")

    c = server.create_app(client_factory=boom).test_client()
    r = c.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth())
    assert r.status_code == 500
    got = _fetch(c, r.headers[server.TRACE_HEADER])
    spans = assert_valid_otlp(got.json["trace"])
    assert _attrs(spans[0])["app.failed_stage"] == "engine"
    assert _attrs(spans[0])["error.type"] == "RuntimeError"
    assert spans[1]["name"] == "engine.run" and spans[1]["status"]["code"] == trace.STATUS_ERROR
    for s in PRIVATE:
        assert s not in got.data.decode("utf-8")


def test_a_503_silo_unavailable_run_still_has_a_trace(monkeypatch):
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)

    def unavailable():
        raise SiloUnavailable()

    c = server.create_app(client_factory=unavailable).test_client()
    r = c.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth())
    assert r.status_code == 503
    spans = assert_valid_otlp(_fetch(c, r.headers[server.TRACE_HEADER]).json["trace"])
    root = _attrs(spans[0])
    assert root["app.http.status"] == "503" and root["error.type"] == "SiloUnavailable"
    assert root["app.failed_stage"] == "engine"


def test_the_store_keeps_only_the_newest_traces(app):
    ids = [app.post("/diagnose", data=b"not a statement", headers=_auth()).headers[server.TRACE_HEADER]
           for _ in range(server.TRACE_STORE_MAX + 2)]
    assert _fetch(app, ids[0]).status_code == 404
    assert _fetch(app, ids[-1]).status_code == 200


def test_git_sha_is_recorded_only_when_it_is_one(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    assert server._git_sha() == "a" * 40
    monkeypatch.setenv("GITHUB_SHA", "main")
    assert server._git_sha() is None
