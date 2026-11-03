"""Emit the OpenAPI 3.1 description of the v2 gateway from its registry.

    python scripts/gen_openapi_v2.py            # writes api-docs/v2/openapi.json
    python scripts/gen_openapi_v2.py --check    # exit 1 when the file is stale

Nothing here is hand-maintained. Every path, parameter, enum and default is
read out of the REGISTRY block of ``supabase/functions/silo-api/registry.ts``
(strict JSON between its BEGIN and END markers, the same block
``tests/test_api_v2_registry.py`` parses), and the error codes out of
``errors.ts``. No Deno, no database. ``tests/test_openapi_v2.py`` fails when the
committed file differs from what this script emits.

The file feeds the Mintlify API playground of the "v2 endpoints (preview)"
group in ``docs.json`` (#1060). Main parameters are enums with their defaults;
hidden parameters are marked in their description. The server is the
``silo-api`` function base, and the public publishable key is prefilled in the
playground's ``apikey`` field with Mintlify's ``x-default`` extension. The
gateway is not deployed yet, so every operation says "preview, not deployed".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FN_DIR = ROOT / "supabase" / "functions" / "silo-api"
REGISTRY_TS = FN_DIR / "registry.ts"
ERRORS_TS = FN_DIR / "errors.ts"
ID_DOCS_TS = ROOT / "supabase" / "functions" / "silo-mcp-v2" / "id_docs.ts"
OUT = ROOT / "api-docs" / "v2" / "openapi.json"

SERVER = "https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-api/v2"
# The public publishable key, the same one api-docs/quickstart.mdx prints. It
# identifies the project, not a person, and maps to the anon role.
PUBLISHABLE_KEY = "sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437"
PREVIEW = "Preview, not deployed. The v2 gateway is built but not deployed yet; this call works once the owner deploys `silo-api`."


def load_registry() -> dict:
    src = REGISTRY_TS.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN REGISTRY\nexport const REGISTRY: Registry = (\{.*?\});\n// END REGISTRY", src, re.S)
    if not m:
        raise SystemExit("the REGISTRY block (between BEGIN and END markers) was not found in registry.ts")
    return json.loads(m.group(1))


def load_error_codes() -> list[str]:
    src = ERRORS_TS.read_text(encoding="utf-8")
    m = re.search(r"export const ERROR_CODES = \[(.*?)\] as const;", src, re.S)
    if not m:
        raise SystemExit("ERROR_CODES was not found in errors.ts")
    return re.findall(r'"([a-z_]+)"', m.group(1))


def load_id_docs() -> dict[str, str]:
    """The per-(endpoint, argument) id phrases MCP v2 uses too (silo-mcp-v2/id_docs.ts)."""
    src = ID_DOCS_TS.read_text(encoding="utf-8")
    m = re.search(r"// BEGIN ID_DOCS\nexport const ID_DOCS: Record<string, string> = (\{.*?\});\n// END ID_DOCS", src, re.S)
    if not m:
        raise SystemExit("the ID_DOCS block (between BEGIN and END markers) was not found in id_docs.ts")
    return json.loads(m.group(1))


def id_key(plan: dict) -> str | None:
    arg = (plan.get("args") or {}).get("id")
    return f"{plan['endpoint']}.{arg}" if arg else None


def id_doc(resource: dict, phrases: dict[str, str]) -> str | None:
    """What id means on this resource, by kind. The same text as idDoc() in id_docs.ts."""
    if "id" not in (resource.get("shared") or []):
        return None
    entries = list((resource.get("kinds") or {}).items())
    single = len(entries) == 1

    def kinds(names: list[str]) -> str:
        return f"{'kinds' if len(names) > 1 else 'kind'} {', '.join(names)}"

    def verb(names: list[str], one: str, many: str) -> str:
        return many if len(names) > 1 else one

    by_phrase: dict[str, list[str]] = {}
    required: list[str] = []
    either: list[str] = []
    empty: dict[str, list[str]] = {}
    none: list[str] = []
    for name, kind in entries:
        key = id_key(kind)
        if not key:
            none.append(name)
            continue
        if key not in phrases:
            raise SystemExit(f"no ID_DOCS phrase for {resource['name']} kind {name} ({key})")
        by_phrase.setdefault(phrases[key], []).append(name)
        req = kind.get("require_one_of") or []
        if req == ["id"]:
            required.append(name)
        elif "id" in req:
            either.append(f"{name}: id or {' or '.join(x for x in req if x != 'id')} is required")
        we = kind.get("when_empty")
        if we and we.get("parameter") == "id":
            empty.setdefault(f"api.{we['plan']['endpoint']}", []).append(name)
    what = [f"{', '.join(names)} {verb(names, 'takes', 'take')} {phrase}" for phrase, names in by_phrase.items()]
    parts = [f"The id is {'; '.join(by_phrase)}." if single else f"By kind: {'; '.join(what)}."]
    if required:
        parts.append(f"Required for {kinds(required)}.")
    parts.extend(f"Kind {e}." for e in either)
    parts.extend(f"With no id, {kinds(n)} {verb(n, 'reads', 'read')} {ep} (what SILO holds)." for ep, n in empty.items())
    if none:
        parts.append(f"K{kinds(none)[1:]} {verb(none, 'takes', 'take')} no id.")
    return " ".join(parts)


def _default_text(p: dict) -> str:
    doc = (p.get("default_doc") or "").rstrip(".")
    if p.get("default") in (None, ""):
        return doc or "none"
    return f"{p['default']} ({doc})" if doc else str(p["default"])


def _schema(p: dict) -> dict:
    t = p["type"]
    has_default = p.get("default") not in (None, "")
    if t == "enum":
        s: dict = {"type": "string", "enum": p["values"]}
    elif t == "date":
        s = {"type": "string", "format": "date"}
    elif t == "integer":
        s = {"type": "integer", "minimum": 1 if p["name"] == "limit" else 0}
    elif t == "number":
        s = {"type": "number", "minimum": 0}
    else:  # string, list (comma-separated in the query string)
        s = {"type": "string"}
    if has_default:
        s["default"] = p["default"]
    return s


def _shared(registry: dict, name: str) -> dict:
    s = registry["shared_parameters"][name]
    t = "date" if name in ("from", "to") else "integer" if name == "limit" else "string"
    return {"name": name, "visibility": "main", "type": t, "default": s["default"], "default_doc": s["default_doc"], "doc": s["doc"]}


def _example_values(resource: dict) -> dict[str, str]:
    """The parameters the registry's own example URL sends (request shapes, not data)."""
    url = resource["example"].split(" ", 2)[1] if resource["example"].startswith("POST ") else resource["example"]
    return dict(parse_qsl(urlsplit(url).query))


def _parameter(p: dict, examples: dict[str, str]) -> dict:
    hidden = p["visibility"] == "hidden"
    lead = "Hidden parameter (`?help=all` lists it). " if hidden else ""
    tail = " Comma-separated list." if p["type"] == "list" else ""
    out = {
        "name": p["name"],
        "in": "query",
        "required": False,
        "description": f"{lead}{p['doc']}{tail} Default: {_default_text(p)}.",
        "schema": _schema(p),
    }
    if p["name"] in examples:
        out["example"] = examples[p["name"]]
    return out


def _description(resource: dict) -> str:
    parts = [f"<Warning>{PREVIEW}</Warning>", resource["summary"], f"Example: `{resource['example']}`"]
    kinds = resource.get("kinds") or {}
    if len(kinds) > 1:
        parts.append("Kinds:\n\n" + "\n".join(f"- `{n}`: {k['doc']}" for n, k in kinds.items()))
    if resource.get("window_months"):
        parts.append(f"With no `from`, a dated kind reads the last {resource['window_months']} months to `to`.")
    for note in resource.get("notes") or []:
        parts.append(note)
    parts.append(f"`GET /v2/{resource['name']}?help` describes the main parameters, `?help=all` adds the hidden ones.")
    return "\n\n".join(parts)


def _responses() -> dict:
    return {
        "200": {"description": "The v2 envelope.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}}},
        "default": {
            "description": "The v2 error object. A SILO refusal (over_limit) keeps its message, hint and details verbatim.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
    }


def _body(resource: dict) -> dict:
    props = {}
    for b in resource["body"]:
        item = {"number": {"type": ["number", "null"]}, "date": {"type": ["string", "null"], "format": "date"}}.get(
            b["items"], {"type": ["string", "null"]}
        )
        props[b["name"]] = {"type": "array", "items": item, "description": f"{b['doc']} Default: {b['default_doc']}."}
    media: dict = {"schema": {"type": "object", "properties": props, "additionalProperties": False}}
    parts = resource["example"].split(" ", 2)
    if len(parts) == 3:  # the registry's own example body: a request shape, not data
        media["example"] = json.loads(parts[2])
    return {
        "required": True,
        "description": "A JSON object of lists. Every other parameter goes in the query string.",
        "content": {"application/json": media},
    }


def _id_parameter(param: dict, resource: dict, phrases: dict[str, str]) -> dict:
    """id means something different on each resource: never the shared generic sentence."""
    doc = id_doc(resource, phrases) if param["name"] == "id" else None
    return {**param, "description": f"{doc} Default: none."} if doc else param


def build(registry: dict, error_codes: list[str]) -> dict:
    phrases = load_id_docs()
    paths: dict = {
        "/": {
            "get": {
                "operationId": "v2_index",
                "summary": "v2 index",
                "description": f"<Warning>{PREVIEW}</Warning>\n\nThe {len(registry['resources'])} resources, one line each, with an example call.",
                "x-mint": {"href": "/api-docs/v2/reference/index"},
                "responses": _responses(),
            }
        }
    }
    for r in registry["resources"]:
        examples = _example_values(r)
        own = r.get("parameters") or []
        shared = [_shared(registry, n) for n in (r.get("shared") or [])]
        if not any(p["name"] == "cursor" for p in shared):
            shared.append(_shared(registry, "cursor"))  # the gateway reads cursor on every resource
        main = [p for p in own if p["visibility"] == "main"]
        hidden = [p for p in own if p["visibility"] == "hidden"]
        op = {
            "operationId": f"v2_{r['name']}",
            "summary": f"v2 {r['name']}",
            "description": _description(r),
            "x-mint": {"href": f"/api-docs/v2/reference/{r['name']}"},
            "parameters": [_id_parameter(_parameter(p, examples), r, phrases) for p in main + shared + hidden],
            "responses": _responses(),
        }
        if r.get("method") == "POST":
            op["requestBody"] = _body(r)
        paths[f"/{r['name']}"] = {(r.get("method") or "GET").lower(): op}

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SILO API v2 (preview, not deployed)",
            "version": registry["version"],
            "description": (
                "The v2 gateway over SILO's schema `api`: 14 resources, five shared parameters, one envelope and one "
                "error object. Generated from supabase/functions/silo-api/registry.ts by scripts/gen_openapi_v2.py; "
                "do not edit by hand. " + PREVIEW
            ),
        },
        "servers": [{"url": SERVER, "description": "The silo-api Edge Function (preview, not deployed)."}],
        "security": [{"apikey": []}, {"apikey": [], "bearerAuth": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "apikey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "apikey",
                    "description": "The public publishable key. It identifies the project, not you, and is the anonymous tier.",
                    "x-default": PUBLISHABLE_KEY,
                },
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "Optional. A user JWT from Supabase Auth, for the signed-in tier. Never a secret key.",
                },
            },
            "schemas": {
                "Envelope": {
                    "type": "object",
                    "required": ["data", "meta"],
                    "properties": {
                        "data": {"type": "array", "items": {}, "description": "Always a list. Rows as the endpoint returned them; null stays null."},
                        "meta": {
                            "type": "object",
                            "required": ["resource", "kind", "request", "id_known"],
                            "properties": {
                                "resource": {"type": "string"},
                                "kind": {"type": ["string", "null"]},
                                "request": {"type": "object", "description": "Every parameter the resource takes, with the default applied."},
                                "id_known": {"type": ["boolean", "null"], "description": "Whether SILO holds the id; null when the call names none."},
                                "endpoint": {"type": "string", "description": "The api.* endpoint that answered."},
                            },
                            "additionalProperties": True,
                        },
                        "next_page_url": {"type": "string", "description": "Present only when more rows remain. It carries one opaque cursor."},
                    },
                },
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message", "target", "innererror"],
                            "properties": {
                                "code": {"type": "string", "enum": error_codes},
                                "message": {"type": "string"},
                                "target": {"type": ["string", "null"]},
                                "innererror": {
                                    "type": "object",
                                    "properties": {
                                        "sqlstate": {"type": ["string", "null"]},
                                        "hint": {"type": ["string", "null"]},
                                        "details": {"type": ["string", "null"]},
                                    },
                                },
                            },
                        }
                    },
                },
            },
        },
    }


def render() -> str:
    return json.dumps(build(load_registry(), load_error_codes()), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when api-docs/v2/openapi.json is stale")
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python scripts/gen_openapi_v2.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(build(load_registry(), load_error_codes())['paths'])} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
