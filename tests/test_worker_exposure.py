"""The owner's trace page (deploy/cloudflare/src/exposure.ts) says the same as scripts/trace_view.py.

Both read the engine JSON; the Worker is TypeScript and the script Python, so this runs the TypeScript with
Node's type stripping on the synthetic demo and compares it with the script's text. Skipped when Node is
missing or too old to import a .ts file.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import trace_view

ROOT = Path(__file__).resolve().parent.parent
EXPOSURE_TS = ROOT / "deploy" / "cloudflare" / "src" / "exposure.ts"
INDEX_TS = ROOT / "deploy" / "cloudflare" / "src" / "index.ts"
DEMO = ROOT / "tests" / "fixtures" / "portfolio" / "demo_engine_output.json"


def _node(script: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    run = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        pytest.skip(f"this node cannot import a .ts file: {run.stderr.strip()[-200:]}")
    return run.stdout


def _call(expr: str) -> str:
    return _node(f"""
import {{ readFileSync }} from "node:fs";
import * as x from {json.dumps(EXPOSURE_TS.as_uri())};
const doc = JSON.parse(readFileSync({json.dumps(str(DEMO))}, "utf8"));
process.stdout.write(JSON.stringify({expr}));
""")


@pytest.mark.parametrize("ticker", ["PETR4", "petr4", "VALEDBS000", "BRSTNCLF1RS0"])
def test_the_worker_text_equals_the_scripts(ticker):
    ts = json.loads(_call(f'x.exposureText(doc, "{ticker}")'))
    assert ts == trace_view.exposure_text(json.loads(DEMO.read_text()), ticker)


def test_an_asset_in_one_line_is_null_in_the_worker():
    assert json.loads(_call('x.exposureText(doc, "XXXX99")')) is None


def test_the_worker_lists_the_same_groups_largest_first():
    groups = json.loads(_call("x.topGroups(doc, 10)"))
    doc = json.loads(DEMO.read_text())
    expected = sorted((g for g in doc["look_through"]["shared_exposure"]["groups"] if g["kind"] == "mesmo_ativo"),
                      key=lambda g: -g["total_exposure_brl"])[:10]
    assert [g["label"] for g in groups] == [g["label"] for g in expected]
    assert groups[0]["total_brl"] >= groups[-1]["total_brl"] and groups[0]["n_lines"] >= 2


def test_the_trace_attribute_reader_finds_the_engine_sha():
    from src.portfolio import trace

    rec = trace.RunRecord(start_ns=1, end_ns=2, status=200, stage="pdf", engine_json=b"{}", pdf=b"%PDF")
    t = json.dumps(trace.build_trace(rec))
    out = _node(f"""
import * as x from {json.dumps(EXPOSURE_TS.as_uri())};
const t = JSON.parse({json.dumps(t)});
process.stdout.write(JSON.stringify([x.traceRootAttribute(t, "app.engine_json.sha256"), x.traceRootAttribute(t, "app.pdf.sha256"), x.traceRootAttribute(t, "nope")]));
""")
    assert json.loads(out) == [trace.sha256_hex(b"{}"), trace.sha256_hex(b"%PDF"), None]


def test_the_routes_are_owner_only_and_read_only_keys():
    src = INDEX_TS.read_text(encoding="utf-8")
    # every /api/traces route sits behind ownerOnly, which fails closed without the secret
    assert re.search(r'pathname\.startsWith\("/api/traces"\) && request\.method === "GET"\) \{\s*const denied = await ownerOnly', src)
    assert 'if (!env.DEMO_ACCESS_TOKEN) return erro(503, "Serviço não configurado.");' in src
    # the bucket is reached only through keys of the two strict shapes
    assert r"const TRACE_KEY = /^traces\/\d{4}\/\d{2}\/\d{2}\/[0-9a-f]{32}\.json$/;" in src
    assert "const SHA256 = /^[0-9a-f]{64}$/;" in src
    # the page shell carries no data; the token is never put in a URL or stored
    page = src[src.index("const TRACES_PAGE"):]
    assert "localStorage" not in page and "sessionStorage" not in page and "?token" not in page
    assert "textContent" in page and "innerHTML" not in page
