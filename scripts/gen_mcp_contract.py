"""Emit the silo-mcp edge function's contract module from openapi.json.

    python scripts/gen_mcp_contract.py            # rewrite the module
    python scripts/gen_mcp_contract.py --check    # exit 1 when it is stale

`openapi.json` is itself generated from the live Postgres catalog
(`scripts/gen_openapi.py`) and pinned to the SQL by `tests/test_openapi_spec.py`.
This script carries that one source one step further, into
`supabase/functions/silo-mcp/contract.generated.ts`: for every published path,
the kind (rpc = POST /rpc/<fn>, view = GET /<view>), the contract prose (the
first paragraph of the operation description — the per-function paging /
row-cap boilerplate that follows it is replaced by one shared line in the
server), and the MCP input schema.

RPC input schemas are the PostgREST request-body schemas verbatim, with two
tightenings that change nothing PostgREST accepts: `additionalProperties:
false` (PostgREST answers an unknown argument with PGRST202 anyway), and a
nullable enum lists `null` as a member so a JSON-schema validator does not
reject the explicit null the SQL takes as its default. View input schemas are
built from the view's column filters: `filters` (column → PostgREST operator
expression), `select`, `order`, `limit`, `offset` — nothing else, so a view
tool can never carry a logical `or=` tree or anything that is not a column.

The edge function hand-lists which of these it exposes (tools.ts);
`tests/test_mcp_contract.py` pins that list to this module and to
`serve/catalog.py`, so the catalog, the OpenAPI spec and the MCP cannot drift.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "openapi.json"
OUT = ROOT / "supabase" / "functions" / "silo-mcp" / "contract.generated.ts"

# The query parameters every view shares; everything else in a view's
# parameter list is a column filter.
VIEW_CONTROL_PARAMS = ("select", "order", "limit", "offset")

# The operators openapi.json documents for view filters. Deliberately no
# `or` / `and` / `not`: a logic tree is a query language, and this server
# does not pass one through.
VIEW_FILTER_OPERATORS = ("eq", "neq", "gt", "gte", "lt", "lte", "in", "is")

IDENT = "[a-z_][a-z0-9_]*"
ORDER_TERM = IDENT + r"(\.(asc|desc))?(\.(nullsfirst|nullslast))?"


def _first_paragraph(description: str) -> str:
    """The contract prose, without the generator's shared **Row cap.** /
    **Paging.** / **Id ceiling.** boilerplate (stated once by the server)."""
    return description.split("\n\n**", 1)[0].strip()


def _tighten(schema: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(schema)
    out["additionalProperties"] = False
    for prop in out.get("properties", {}).values():
        types = prop.get("type")
        nullable = isinstance(types, list) and "null" in types
        if nullable and "enum" in prop and None not in prop["enum"]:
            prop["enum"] = [*prop["enum"], None]
    return out


def _view_schema(columns: list) -> Dict[str, Any]:
    op_pattern = "^(" + "|".join(VIEW_FILTER_OPERATORS) + r")\."
    return {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "description": (
                    "PostgREST column filters, column -> '<op>.<value>' with op in "
                    + ", ".join(VIEW_FILTER_OPERATORS)
                    + " (e.g. {\"ticker\": \"eq.PETR4\", \"trade_date\": "
                    "\"gte.2026-09-01\"}; in takes 'in.(A,B)'; is takes "
                    "'is.null'). One filter per column."
                ),
                "properties": {
                    col: {"type": "string", "pattern": op_pattern} for col in columns
                },
                "additionalProperties": False,
            },
            "select": {
                "type": "string",
                "description": "Columns to return, comma separated. Omit for all.",
                "pattern": f"^{IDENT}(,{IDENT})*$",
            },
            "order": {
                "type": "string",
                "description": (
                    "Sort, e.g. 'trade_date.desc,ticker.asc'. Always order a "
                    "paged read, or limit/offset walk an undefined sequence."
                ),
                "pattern": f"^{ORDER_TERM}(,{ORDER_TERM})*$",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Rows to return (the server cuts every response at 1000).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Rows to skip. Pairs with limit and order to page.",
            },
        },
        "additionalProperties": False,
    }


def build(openapi: Dict[str, Any]) -> Dict[str, Any]:
    entries: Dict[str, Any] = {}
    for path in sorted(openapi["paths"]):
        item = openapi["paths"][path]
        if path.startswith("/rpc/"):
            op = item["post"]
            name = path[len("/rpc/"):]
            body = op["requestBody"]["content"]["application/json"]["schema"]
            schema = _tighten(body)
            schema.pop("description", None)
            entries[name] = {
                "kind": "rpc",
                "path": path,
                "description": _first_paragraph(op.get("description", "")),
                "inputSchema": schema,
            }
        else:
            op = item["get"]
            name = path.lstrip("/")
            columns = [
                p["name"]
                for p in op.get("parameters", [])
                if "name" in p and p["name"] not in VIEW_CONTROL_PARAMS
            ]
            entries[name] = {
                "kind": "view",
                "path": path,
                "description": _first_paragraph(op.get("description", "")),
                "columns": columns,
                "inputSchema": _view_schema(columns),
            }
    return entries


def render(openapi: Dict[str, Any]) -> str:
    version = str(openapi["info"]["version"])
    entries = build(openapi)
    body = json.dumps(entries, indent=2, ensure_ascii=False, sort_keys=False)
    return (
        "// GENERATED by scripts/gen_mcp_contract.py from openapi.json — do not edit.\n"
        "// Regenerate after gen_openapi.py; tests/test_mcp_contract.py fails when stale.\n"
        "\n"
        "export interface ContractEntry {\n"
        '  kind: "rpc" | "view";\n'
        "  path: string;\n"
        "  description: string;\n"
        "  columns?: string[];\n"
        "  inputSchema: Record<string, unknown>;\n"
        "}\n"
        "\n"
        f"export const CONTRACT_VERSION = {json.dumps(version)};\n"
        "\n"
        f"export const CONTRACT: Record<string, ContractEntry> = {body};\n"
    )


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the module is stale")
    args = ap.parse_args(argv)
    text = render(json.loads(OPENAPI.read_text(encoding="utf-8")))
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale; run scripts/gen_mcp_contract.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(build(json.loads(OPENAPI.read_text(encoding='utf-8'))))} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
