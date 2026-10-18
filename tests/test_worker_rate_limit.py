"""#892: the Worker's Workers Rate Limiting binding, run against the real src/index.ts with a fake limiter.

A request over the limit gets 429 with Retry-After, the key is the token's digest plus the route (never the
raw token, never the IP), and a missing binding fails closed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_TS = ROOT / "deploy/cloudflare/src/index.ts"
WRANGLER = ROOT / "deploy/cloudflare/wrangler.jsonc"
NODE = shutil.which("node")
TOKEN = "synthetic-demo-token"

LOADER = """
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
"""

RUNNER = """
import { timingSafeEqual } from "node:crypto";
crypto.subtle.timingSafeEqual = (a, b) => timingSafeEqual(Buffer.from(a), Buffer.from(b));
const x = await import(process.argv[2]);
const [method, path, mode, token] = process.argv.slice(3);
const keys = [];
const limiter = mode === "missing" ? undefined : { async limit({ key }) { keys.push(key); return { success: mode !== "over" }; } };
let started = 0;
globalThis.testContainer = {
  async fetch() { started++; return new Response("ok", { status: 200, headers: { "content-type": "text/html" } }); },
  async stop() {}, async destroy() {}
};
const headers = token === "-" ? {} : { "x-demo-token": token };
const response = await x.default.fetch(new Request("https://worker.invalid" + path, { method, headers, body: method === "POST" ? "upload" : undefined }),
  { ENGINE: {}, TRACES: { async put() {}, async list() { return { objects: [] }; } }, DEMO_ACCESS_TOKEN: "%(token)s",
    DIAGNOSE_LIMITER: limiter, TRACES_LIMITER: limiter },
  { waitUntil() {} });
await response.text();
process.stdout.write(JSON.stringify({ status: response.status, retryAfter: response.headers.get("retry-after"), keys, started }));
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not NODE:
        pytest.skip("Worker behavioral tests require Node 22 or newer")
    version = subprocess.check_output([NODE, "--version"], text=True)
    if int(version.lstrip("v").split(".")[0]) < 22:
        pytest.skip("Worker behavioral tests require Node 22 or newer")
    folder = tmp_path_factory.mktemp("worker-limit")
    (folder / "loader.mjs").write_text(LOADER)
    (folder / "run.mjs").write_text(RUNNER % {"token": TOKEN})
    return folder


def call(harness, method, path, mode="under", token=TOKEN):
    run = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", "--loader", str(harness / "loader.mjs"),
                          str(harness / "run.mjs"), INDEX_TS.as_uri(), method, path, mode, token],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_diagnose_over_the_limit_is_429_with_retry_after_and_starts_nothing(harness):
    out = call(harness, "POST", "/diagnose", "over")
    assert out["status"] == 429 and out["retryAfter"] == "60" and out["started"] == 0


def test_diagnose_under_the_limit_goes_through(harness):
    out = call(harness, "POST", "/diagnose", "under")
    assert out["status"] == 200 and out["started"] == 1 and out["retryAfter"] is None


def test_the_key_is_the_token_digest_plus_the_route_never_the_raw_token(harness):
    import hashlib

    digest = hashlib.sha256(TOKEN.encode()).hexdigest()
    assert call(harness, "POST", "/diagnose")["keys"] == [f"/diagnose:{digest}"]
    assert call(harness, "GET", "/api/traces")["keys"] == [f"/api/traces:{digest}"]
    assert call(harness, "GET", "/api/traces/pdf")["keys"] == [f"/api/traces/pdf:{digest}"]
    assert TOKEN not in json.dumps(call(harness, "POST", "/diagnose")["keys"])


def test_the_trace_reads_are_limited_too(harness):
    out = call(harness, "GET", "/api/traces", "over")
    assert out["status"] == 429 and out["retryAfter"] == "60"


def test_a_missing_binding_fails_closed(harness):
    assert call(harness, "POST", "/diagnose", "missing")["status"] == 503
    assert call(harness, "GET", "/api/traces", "missing")["status"] == 503


@pytest.mark.parametrize("method,path", [("POST", "/diagnose"), ("GET", "/api/traces")])
def test_a_wrong_or_absent_token_is_401_and_spends_no_count(harness, method, path):
    for token in ("wrong-token", "-"):
        out = call(harness, method, path, "over", token)
        assert out["status"] == 401 and out["keys"] == []


def test_the_public_routes_are_not_limited(harness):
    out = call(harness, "GET", "/health", "over")
    assert out["status"] == 200 and out["keys"] == []


def test_wrangler_declares_both_bindings_and_the_retry_after_matches_the_period():
    cfg = WRANGLER.read_text(encoding="utf-8")
    for name in ("DIAGNOSE_LIMITER", "TRACES_LIMITER"):
        assert f'"name": "{name}"' in cfg
    ids = re.findall(r'"namespace_id": "(\d+)"', cfg)
    assert len(ids) == len(set(ids)) == 2
    assert set(re.findall(r'"period": (\d+)', cfg)) == {"60"}
    assert "const LIMIT_PERIOD_SECONDS = 60;" in INDEX_TS.read_text(encoding="utf-8")
