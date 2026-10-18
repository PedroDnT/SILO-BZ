"""Execute the actual Worker with fake platform I/O and await background work."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not NODE:
        pytest.skip("Worker behavioral tests require Node 22 or newer")
    version = subprocess.check_output([NODE, "--version"], text=True)
    if int(version.lstrip("v").split(".")[0]) < 22:
        pytest.skip("Worker behavioral tests require Node 22 or newer")
    folder = tmp_path_factory.mktemp("worker-trace")
    loader = folder / "loader.mjs"
    loader.write_text('''
import { existsSync } from "node:fs";
export async function resolve(specifier, context, nextResolve) {
  if (specifier === "@cloudflare/containers") {
    const source = "export class Container {} export class ContainerProxy {} export function getContainer() { return globalThis.testContainer; }";
    return { url: "data:text/javascript," + encodeURIComponent(source), shortCircuit: true };
  }
  if (specifier.startsWith("./") && context.parentURL?.endsWith(".ts")) {
    const candidate = new URL(specifier + ".ts", context.parentURL);
    if (existsSync(candidate)) return nextResolve(candidate.href, context);
  }
  return nextResolve(specifier, context);
}
''')
    runner = folder / "run.mjs"
    runner.write_text('''
import { timingSafeEqual } from "node:crypto";
crypto.subtle.timingSafeEqual = (a, b) => timingSafeEqual(Buffer.from(a), Buffer.from(b));
const x = await import(process.argv[2]);
const scenario = process.argv[3];
const secret = "synthetic-sensitive-portfolio-and-token";
const id = "ab".repeat(16);
const logs = [];
console.info = (text) => logs.push(JSON.parse(text));
const sha = async (s) => Buffer.from(await crypto.subtle.digest("SHA-256", Buffer.from(s))).toString("hex");
const engine = JSON.stringify({ portfolio: secret });
const html = "<html>" + secret + "</html>";
const engineSha = await sha(engine), htmlSha = await sha(html);
const attributes = [
  { key: "app.engine_json.sha256", value: { stringValue: engineSha } },
  { key: "app.html.sha256", value: { stringValue: htmlSha } }
];
const bundle = {
  trace_id: id,
  trace: { resourceSpans: [{ scopeSpans: [{ spans: [{ traceId: id, attributes }] }] }] },
  artifacts: { ["artifacts/" + engineSha + ".json"]: Buffer.from(engine).toString("base64"),
               ["artifacts/" + htmlSha + ".html"]: Buffer.from(html).toString("base64") },
};
if (scenario === "mismatched_id") bundle.trace_id = secret;
if (scenario === "missing_artifact") delete bundle.artifacts["artifacts/" + htmlSha + ".html"];
if (scenario === "bad_hash") bundle.artifacts["artifacts/" + htmlSha + ".html"] = Buffer.from("wrong").toString("base64");
if (scenario === "invalid_key") bundle.artifacts[secret] = Buffer.from(secret).toString("base64");
if (scenario === "invalid_document") bundle.documents = { ["docs/web/doc/" + "0".repeat(64) + ".txt"]: Buffer.from(secret).toString("base64") };
if (scenario === "missing_pdf") attributes.push({ key: "app.pdf.sha256", value: { stringValue: "1".repeat(64) } });
if (scenario === "pdf_ok") attributes.push({ key: "app.pdf.sha256", value: { stringValue: await sha("%PDF synthetic") } });
let stopped = 0, pending = [], puts = [], completedWrites = 0, writesAtStop = -1;
let releaseFetch;
const delayedFetch = new Promise(resolve => { releaseFetch = resolve; });
globalThis.testContainer = {
  async fetch(request) {
    if (new URL(request.url).pathname === "/diagnose") {
      return new Response(scenario === "pdf_ok" ? "%PDF synthetic" : "diagnosis result", { status: 200,
        headers: { "content-type": scenario === "pdf_ok" ? "application/pdf" : "text/html", "x-silo-trace-id": id } });
    }
    await delayedFetch;
    if (scenario === "fetch_throw") throw new Error(secret);
    if (scenario === "http_error") return new Response(secret, { status: 503 });
    if (scenario === "bad_json") return new Response(secret);
    if (scenario === "invalid_bundle") return Response.json({ trace_id: id, trace: secret, artifacts: {} });
    return Response.json(bundle);
  },
  async stop() { stopped++; writesAtStop = completedWrites; if (scenario === "stop_throw") throw new Error(secret); },
  async destroy() {}
};
const bucket = {
  async put(key, body) {
    puts.push(key);
    if (scenario === "artifact_throw" && key.endsWith(".html")) throw new Error(secret);
    if (scenario === "trace_throw" && key.startsWith("traces/")) throw new Error(secret);
    await new Promise(resolve => setTimeout(resolve, 3));
    completedWrites++;
  }
};
const response = await x.default.fetch(new Request("https://worker.invalid/diagnose", {
  method: "POST", headers: { "x-demo-token": secret }, body: "synthetic upload"
}), { ENGINE: {}, DIAGNOSE_LIMITER: { async limit() { return { success: true }; } }, TRACES: scenario === "no_bucket" ? undefined : bucket, DEMO_ACCESS_TOKEN: secret },
{ waitUntil(promise) { pending.push(promise); } });
const body = await response.text();
const responseBeforePersistence = puts.length === 0;
releaseFetch();
await Promise.all(pending);
process.stdout.write(JSON.stringify({ status: response.status, body, logs, puts, stopped,
  responseBeforePersistence, completedWrites, writesAtStop,
  storageHeader: response.headers.get("x-silo-trace-storage"), key: response.headers.get("x-silo-trace-key") }));
''')
    return loader, runner


def execute(harness, scenario):
    loader, runner = harness
    result = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", "--loader", str(loader),
                             str(runner), (ROOT / "deploy/cloudflare/src/index.ts").as_uri(), scenario],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["status"] == 200
    assert value["body"] == ("%PDF synthetic" if scenario == "pdf_ok" else "diagnosis result")
    assert value["stopped"] == 1
    assert value["responseBeforePersistence"] is True
    assert "synthetic-sensitive-portfolio-and-token" not in json.dumps(value["logs"])
    persistence = [e for e in value["logs"] if e["event"] == "trace_persistence"]
    assert len(persistence) == 1
    assert set(persistence[0]) == {"event", "status", "reason"}
    assert value["writesAtStop"] == value["completedWrites"]
    return value, persistence[0]


@pytest.mark.parametrize("scenario", ["html_ok", "pdf_ok", "stop_throw"])
def test_complete_artifacts_are_stored_before_trace_and_cleanup(harness, scenario):
    value, outcome = execute(harness, scenario)
    assert outcome == {"event": "trace_persistence", "status": "stored", "reason": "complete"}
    assert value["puts"][-1].startswith("traces/")
    assert value["storageHeader"] == "pending" and value["key"].startswith("traces/")
    if scenario == "stop_throw":
        assert value["logs"][-1] == {"event": "container_cleanup", "status": "failed", "reason": "stop_failed"}


@pytest.mark.parametrize("scenario,status,reason", [
    ("fetch_throw", "failed", "trace_fetch_failed"),
    ("http_error", "failed", "trace_http_error"),
    ("bad_json", "incomplete", "invalid_bundle"),
    ("invalid_bundle", "incomplete", "invalid_bundle"),
    ("mismatched_id", "incomplete", "trace_id_mismatch"),
    ("missing_artifact", "incomplete", "missing_artifact"),
    ("bad_hash", "incomplete", "invalid_hash"),
    ("invalid_key", "incomplete", "invalid_key"),
    ("invalid_document", "incomplete", "invalid_hash"),
    ("missing_pdf", "incomplete", "missing_artifact"),
    ("artifact_throw", "failed", "artifact_write_failed"),
    ("trace_throw", "failed", "trace_write_failed"),
    ("no_bucket", "skipped", "bucket_unavailable"),
])
def test_failures_are_sanitized_and_do_not_fail_the_diagnosis(harness, scenario, status, reason):
    value, outcome = execute(harness, scenario)
    assert outcome["status"] == status and outcome["reason"] == reason
    if status == "incomplete" or scenario in {"fetch_throw", "http_error", "no_bucket"}:
        assert value["puts"] == []
    elif scenario == "artifact_throw":
        assert not any(k.startswith("traces/") for k in value["puts"])
