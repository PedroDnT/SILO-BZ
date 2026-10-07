"""Emit the Python SDK's RPC contract from openapi.json.

    python scripts/gen_sdk_contract.py            # rewrite the file
    python scripts/gen_sdk_contract.py --check    # exit 1 when it is stale

`openapi.json` is generated from the live Postgres catalog
(`scripts/gen_openapi.py`) and pinned to the SQL by `tests/test_openapi_spec.py`.
This script carries the part the SDK needs into
`sdk/silo_client/contract.json`, which ships inside the package: for every
`POST /rpc/<fn>`, the parameter names its request body declares and the ones it
requires. `SiloClient.rpc()` checks a call against it before any request is
sent, so a typo in a function or argument name fails offline instead of coming
back as PostgREST's 404 against a function that exists.

Only names, never the prose: the descriptions change with every catalog
version, the signatures only when an endpoint does. `tests/test_sdk_rpc.py`
fails while the file is stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "openapi.json"
OUT = ROOT / "sdk" / "silo_client" / "contract.json"


def build(openapi: Dict[str, Any]) -> Dict[str, Dict[str, list]]:
    """{function: {"params": [...], "required": [...]}}, both sorted."""
    out: Dict[str, Dict[str, list]] = {}
    for path, ops in openapi["paths"].items():
        if not path.startswith("/rpc/"):
            continue
        body = (ops.get("post") or {}).get("requestBody") or {}
        schema = body.get("content", {}).get("application/json", {}).get("schema", {})
        out[path[len("/rpc/"):]] = {
            "params": sorted(schema.get("properties", {})),
            "required": sorted(schema.get("required", [])),
        }
    return dict(sorted(out.items()))


def render(openapi: Dict[str, Any]) -> str:
    return json.dumps({"rpc": build(openapi)}, indent=1, ensure_ascii=False) + "\n"


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args(argv)
    text = render(json.loads(OPENAPI.read_text(encoding="utf-8")))
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale; run scripts/gen_sdk_contract.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(json.loads(text)['rpc'])} functions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
