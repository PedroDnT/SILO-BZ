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
    # the page shell carries no data; the token is never put in a URL, and it is stored only on the owner's
    # opt-in (2026-10-07): in this browser's localStorage, every access inside try/catch, with a way to forget it
    for name in ("const PAGE = `", "const TRACES_PAGE = `"):
        page = src[src.index(name):]
        page = page[:page.index("</html>")]
        assert "sessionStorage" not in page and "?token" not in page and "token=" not in page
        assert page.count("localStorage") == 3
        for line in page.splitlines():
            if "localStorage." in line:
                assert "try {" in line and "catch (_)" in line, line
        assert 'id="remember" type="checkbox"' in page and 'id="forget"' in page
        assert "Lembrar neste aparelho" in page and "não fica guardado" not in page
    page = src[src.index("const TRACES_PAGE"):]
    assert "textContent" in page and "innerHTML" not in page


def test_the_list_reaches_back_30_days_and_100_runs_and_a_run_has_its_own_link():
    src = INDEX_TS.read_text(encoding="utf-8")
    assert "const MAX_LIST_DAYS = 30;" in src and "const MAX_LIST_TRACES = 100;" in src
    lister = src[src.index("async function listTraces"):src.index("async function readTrace")]
    assert ", 1), MAX_LIST_DAYS)" in lister and "found.slice(0, MAX_LIST_TRACES)" in lister
    assert "limit: 100" in lister  # one R2 list per UTC day, as before
    page = src[src.index("const TRACES_PAGE"):]
    for days in ("3", "7", "14", "30"):
        assert f'<option value="{days}"' in page
    assert "location.hash" in page and '"hashchange"' in page
    # the upload answer names the key the trace is written to, built as storeTrace builds it
    assert 'headers.set(TRACE_KEY_HEADER, `traces/${day}/${traceId}.json`)' in src
    assert 'await bucket.put(`traces/${day}/${traceId}.json`' in src
    assert 'r.headers.get("x-silo-trace-key")' in src


def test_the_flow_lists_each_line_with_what_it_puts_in():
    flows = json.loads(_call('x.exposureFlows(doc, "petr4")'))
    assert len(flows) == 1
    f = flows[0]
    assert f["ativo"]["label"].startswith("PETR4") and f["extrato_em"] and f["cda_mes"]
    direct = next(s for s in f["fontes"] if s["direto"])
    fund = next(s for s in f["fontes"] if not s["direto"])
    assert direct["nome"] == "PETROBRAS PN" and direct["exposicao_brl"] == 988000.0 and direct["posicao_brl"] == 988000.0
    assert direct["peso_no_fundo_pct"] is None and direct["cda"] is None
    assert fund["nome"] == "GERAÇÃO L. PAR FIA" and fund["cda"] == "2026-05"
    assert round(fund["peso_no_fundo_pct"], 2) == 16.59 and fund["posicao_brl"] > fund["exposicao_brl"]
    # the age of the CDA is two engine dates apart in calendar months, never a clock reading
    assert fund["cda_idade_meses"] == 4 and sum(s["exposicao_brl"] for s in f["fontes"]) == pytest.approx(f["ativo"]["total_brl"])


def test_the_flow_of_an_asset_in_one_line_is_empty():
    assert json.loads(_call('x.exposureFlows(doc, "XXXX99")')) == []


def test_the_page_script_draws_with_text_nodes_and_no_template_literals():
    src = INDEX_TS.read_text(encoding="utf-8")
    start = src.index("<script>", src.index("const TRACES_PAGE"))
    script = src[start:src.index("</script>", start)]
    # the page is a TS template literal: a backtick, ${ or backslash in it would be consumed by TypeScript
    assert "`" not in script and "${" not in script and "\\" not in script
    assert "innerHTML" not in script and script.count("textContent") >= 3
