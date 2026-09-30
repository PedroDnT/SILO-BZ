"""Check the PUBLISHED contract against this checkout: REST API and remote MCP.

    python scripts/check_live_contract.py            # exit 1 on any mismatch

The offline tests pin the catalog, openapi.json and the MCP contract module to
each other. They cannot see what production serves: a merge deploys neither
the analytical SQL nor the edge function (AGENTS.md, Deploy). This script asks
the live endpoints, with the public key only, and compares:

  1. versions   api.catalog() over REST, the MCP `catalog` tool, and the MCP
                server's `contract-<n>` against serve/catalog.py;
  2. tools      the MCP tools/list names against the t() lines in tools.ts;
  3. arguments  every MCP tool's input schema (argument names, required list,
                defaults, enums) against the contract generated from this
                checkout's openapi.json, exactly;
  4. results    the same quote_history calls answered over REST and through the
                MCP, with the default fields and with the raw close selected:
                identical rows, the default carrying only ticker, trade_date
                and close_adj.

Stdlib only, so the deploy workflow runs it with the runner's python3.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gen_mcp_contract import build  # noqa: E402

DEFAULT_BASE = "https://zcjbtpxuhdekpwcxmepn.supabase.co"
# The publishable key: public by design, printed in the docs and shipped in
# the SDK (sdk/silo_client/client.py DEFAULT_ANON_KEY).
DEFAULT_KEY = "sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437"
TOOLS_TS = ROOT / "supabase/functions/silo-mcp/tools.ts"
OPENAPI = ROOT / "openapi.json"

# A liquid share with a long history; the window is fixed so both surfaces
# answer the same question.
PROBE = {"p_ticker": "PETR4", "p_from": "2026-06-01", "p_to": "2026-06-30"}


def _post(url: str, body: Any, headers: dict[str, str]) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def rest(base: str, key: str, fn: str, body: dict[str, Any]) -> tuple[int, Any, dict[str, str]]:
    status, text, headers = _post(f"{base}/rest/v1/rpc/{fn}", body,
                                  {"apikey": key, "accept": "application/json"})
    return status, (json.loads(text) if text else None), headers


def mcp(base: str, method: str, params: dict[str, Any]) -> Any:
    status, text, _ = _post(
        f"{base}/functions/v1/silo-mcp",
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        {"accept": "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18"},
    )
    if status != 200:
        raise RuntimeError(f"MCP {method}: HTTP {status}: {text[:300]}")
    t = text.lstrip()
    payload = t if t.startswith("{") else "".join(l[5:] for l in t.splitlines() if l.startswith("data:"))
    msg = json.loads(payload)
    if "error" in msg:
        raise RuntimeError(f"MCP {method}: {msg['error']}")
    return msg["result"]


def mcp_tool_json(base: str, name: str, args: dict[str, Any]) -> tuple[bool, Any, str]:
    """Call an MCP tool; return (is_error, parsed JSON payload, raw text)."""
    res = mcp(base, "tools/call", {"name": name, "arguments": args})
    text = res["content"][0]["text"]
    if res.get("isError"):
        return True, None, text
    # "rows: n\nprovenance: ...\n[data_revision: ...\n]<json>": the JSON is the
    # last line.
    return False, json.loads(text.rsplit("\n", 1)[-1]), text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--key", default=DEFAULT_KEY)
    args = ap.parse_args(argv)

    from serve.catalog import CATALOG_VERSION

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            problems.append(what)

    # 1. Versions.
    _, cat, _ = rest(args.base, args.key, "catalog", {})
    check(isinstance(cat, dict) and cat.get("version") == CATALOG_VERSION,
          f"REST api.catalog() version {cat.get('version') if isinstance(cat, dict) else cat!r} == {CATALOG_VERSION}")
    init = mcp(args.base, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "check_live_contract", "version": "1"},
    })
    served = init.get("serverInfo", {}).get("version")
    check(served == f"contract-{CATALOG_VERSION}", f"MCP server version {served!r} == contract-{CATALOG_VERSION}")
    err, mcat, _ = mcp_tool_json(args.base, "catalog", {})
    check(not err and isinstance(mcat, dict) and mcat.get("version") == CATALOG_VERSION,
          f"MCP catalog tool version {mcat.get('version') if isinstance(mcat, dict) else mcat!r} == {CATALOG_VERSION}")

    # 2. Tools.
    expected_tools = re.findall(r'^\s*t\("([a-z_]+)"', TOOLS_TS.read_text(encoding="utf-8"), re.M)
    live = mcp(args.base, "tools/list", {})["tools"]
    live_by_name = {t["name"]: t for t in live}
    check(sorted(live_by_name) == sorted(expected_tools),
          f"MCP tools: {len(live_by_name)} live, {len(expected_tools)} in tools.ts, "
          f"missing {sorted(set(expected_tools) - set(live_by_name))}, extra {sorted(set(live_by_name) - set(expected_tools))}")

    # 3. Arguments and defaults: the served input schema IS the contract's.
    contract = build(json.loads(OPENAPI.read_text(encoding="utf-8")))
    drift = [n for n in expected_tools
             if n in live_by_name and live_by_name[n].get("inputSchema") != contract[n]["inputSchema"]]
    check(not drift, f"MCP input schemas equal the contract (drifted: {drift})")

    # 4. Results: the same call over REST and through the MCP.
    for label, extra in (("default fields", {}), ("raw close selected", {"p_fields": ["close"]})):
        body = {**PROBE, **extra}
        status, rows, headers = rest(args.base, args.key, "quote_history", body)
        err, mrows, mtext = mcp_tool_json(args.base, "quote_history", body)
        check(status == 200 and isinstance(rows, list) and rows, f"REST quote_history ({label}) answers rows (HTTP {status})")
        check(not err and mrows == rows, f"MCP quote_history ({label}) returns the REST rows" + (f": {mtext[:200]}" if err else ""))
        want = {"ticker", "trade_date", "close_adj"} if not extra else {"ticker", "trade_date", "close"}
        check(isinstance(rows, list) and all(set(r) == want for r in rows),
              f"quote_history ({label}) rows carry exactly {sorted(want)}")
        rev = {k.lower(): v for k, v in headers.items()}.get("x-silo-data-revision")
        check(bool(rev) and f"data_revision: {rev}" in mtext, f"data revision {rev!r} reported over REST and MCP ({label})")

    status, _, _ = rest(args.base, args.key, "quote_history", {**PROBE, "p_fields": ["nope"]})
    check(status == 400, f"an unknown field is refused (HTTP {status})")

    print(f"\n{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
