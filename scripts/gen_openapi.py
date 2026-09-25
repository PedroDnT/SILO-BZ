"""Emit the OpenAPI 3.1 description of schema `api` by reading the live catalog.

    POSTGRES_URL=... python scripts/gen_openapi.py > openapi.json

The point of this script is that NOTHING here is hand-maintained. Every path,
parameter, column and type is read back out of Postgres — `pg_proc` +
`pg_get_function_arguments` for the RPCs, `information_schema.columns` for the
views — and the object set is exactly "what `anon` was granted", which is the
same question the five endpoints that shipped live and undocumented answered
wrong. A signature that changes in `19_api_contract.sql` changes here on the
next run or it does not change at all.

The behavioural half of the contract (what a function does ABOVE one page) is
introspected too, not asserted: a function that calls `api.assert_row_cap`
REFUSES with SQLSTATE 22023, a function that branches on `api.caller_tier()`
CLAMPS to a per-tier ceiling, and a function taking `p_after` offers a cursor.
Those three predicates are read off `pg_proc.prosrc`, so the spec cannot claim
a cap the SQL does not enforce.

`serve/catalog.py`'s LIMITS block is the authority for the numbers; this script
reads the same numbers out of the deployed function bodies so the two are
pinned to one source. `tests/test_openapi_spec.py` is the offline guard that
fails when the committed `openapi.json` and the SQL disagree.

Requires a database with the analytical layer applied. Any Postgres carrying
`19_api_contract.sql` + `20_short_interest.sql` + `21_lending_participants.sql`
will do — the CI `sql-compile` path (an empty throwaway cluster with
`PGOPTIONS=-c silo.ci_smoke_bypass=on`) is enough, because only the catalog is
read and never a row of data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

import psycopg2

# The published Data API. Views hang off the root, functions off /rpc/.
SERVER_URL = "https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1"

# PostgREST db-max-rows. Server-wide, identical for every tier; it is the page
# size the capped functions refuse above rather than trim to.
PAGE_SIZE = 1000

SPEC_VERSION = "3.1.0"

# --------------------------------------------------------------------------
# Catalog queries. "Granted" means `anon` holds the privilege — anon is the
# published surface, and `authenticated` is anon plus a bigger ceiling, never a
# wider object set.
# --------------------------------------------------------------------------

FUNCTIONS_SQL = """
SELECT p.proname,
       pg_get_function_arguments(p.oid)                AS args,
       pg_get_function_result(p.oid)                   AS result,
       p.proretset                                     AS returns_set,
       obj_description(p.oid, 'pg_proc')               AS comment,
       p.prosrc                                        AS src,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') AS auth_granted
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'api'
   AND has_function_privilege('anon', p.oid, 'EXECUTE')
 ORDER BY p.proname
"""

VIEWS_SQL = """
SELECT c.relname,
       obj_description(c.oid, 'pg_class') AS comment
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'api'
   AND c.relkind IN ('v', 'm', 'r')
   AND has_table_privilege('anon', c.oid, 'SELECT')
 ORDER BY c.relname
"""

COLUMNS_SQL = """
SELECT table_name, column_name, data_type, udt_name, ordinal_position
  FROM information_schema.columns
 WHERE table_schema = 'api'
 ORDER BY table_name, ordinal_position
"""

# The internal helpers a granted function may delegate its ceilings to. Their
# bodies are scanned alongside the caller's so a cap expressed one call away
# (api.panel's id ceiling lives in api.assert_panel_ids) is still found.
HELPERS_SQL = """
SELECT p.proname, p.prosrc
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'api'
   AND NOT has_function_privilege('anon', p.oid, 'EXECUTE')
"""


# --------------------------------------------------------------------------
# Postgres type -> JSON Schema
# --------------------------------------------------------------------------

_SCALARS: dict[str, dict[str, Any]] = {
    "text": {"type": "string"},
    "character varying": {"type": "string"},
    "date": {"type": "string", "format": "date"},
    "timestamp with time zone": {"type": "string", "format": "date-time"},
    "timestamp without time zone": {"type": "string", "format": "date-time"},
    "numeric": {"type": "number"},
    "double precision": {"type": "number"},
    "real": {"type": "number"},
    "integer": {"type": "integer", "format": "int32"},
    "smallint": {"type": "integer", "format": "int32"},
    "bigint": {"type": "integer", "format": "int64"},
    "boolean": {"type": "boolean"},
    "jsonb": {"type": "object"},
    "json": {"type": "object"},
}


def pg_type_to_schema(pg_type: str) -> dict[str, Any]:
    """Map a Postgres type name to a JSON Schema fragment, nullable.

    Every column and every OUT parameter in schema `api` can be NULL — a null
    inside a family's applicable columns is a blank in that month's filing, a
    null outside it is "not applicable by construction". Neither is an error,
    so the schema says so rather than pretending the columns are required.
    """
    t = pg_type.strip().lower()
    t = re.sub(r"\s+default\b.*$", "", t)

    if t.endswith("[]"):
        inner = pg_type_to_schema(t[:-2])
        return {"type": ["array", "null"], "items": inner}
    if t.startswith("array of ") or t == "array":
        return {"type": ["array", "null"], "items": {"type": "string"}}

    base = _SCALARS.get(t)
    if base is None:
        # Unknown/domain type: describe it honestly rather than guessing a
        # shape. `format` carries the Postgres name so the page still says
        # what it is.
        return {"type": ["string", "null"], "format": t}

    out: dict[str, Any] = dict(base)
    out["type"] = [out["type"], "null"]
    return out


# --------------------------------------------------------------------------
# Signature / behaviour parsing
# --------------------------------------------------------------------------

_ARG_SPLIT = re.compile(r",(?![^()\[\]]*[)\]])")


def split_top_level(text: str) -> list[str]:
    """Split a comma list, ignoring commas inside (), [] or quotes."""
    parts: list[str] = []
    depth = 0
    quoted = False
    current: list[str] = []
    for ch in text:
        if ch == "'":
            quoted = not quoted
        if not quoted:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_arguments(args: str) -> list[dict[str, Any]]:
    """`pg_get_function_arguments` text -> [{name, type, default}]."""
    out: list[dict[str, Any]] = []
    for raw in split_top_level(args):
        if not raw:
            continue
        m = re.match(
            r"^(?:VARIADIC\s+|OUT\s+|INOUT\s+|IN\s+)?"
            r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+"
            r"(?P<type>.+?)"
            r"(?:\s+DEFAULT\s+(?P<default>.+))?$",
            raw.strip(),
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            continue
        out.append(
            {
                "name": m.group("name"),
                "type": m.group("type").strip(),
                "default": (m.group("default") or "").strip() or None,
            }
        )
    return out


def pg_default_to_json(expr: str) -> tuple[bool, Any]:
    """A Postgres DEFAULT expression -> (representable, JSON value).

    The prose `Defaults to \\`…\\`.` always carries the raw expression; this is
    the machine-readable half, so a request builder can PRE-FILL the field
    instead of making the reader parse English.

    Only literals are representable. `CURRENT_DATE - 365` is a value the server
    computes per request — emitting today's date as a static `default` would
    freeze it into the spec and be wrong tomorrow — so it stays prose-only.
    """
    e = expr.strip()
    e = re.sub(r"^\((.*)\)$", r"\1", e).strip()  # (CURRENT_DATE - 365) -> CURRENT_DATE - 365

    # ARRAY[...] first: its elements carry their own casts, and stripping a
    # trailing `::text]` off the whole expression would corrupt the literal.
    arr = re.fullmatch(r"ARRAY\s*\[(?P<body>.*)\]", e, re.DOTALL | re.IGNORECASE)
    if arr:
        items: list[Any] = []
        for part in split_top_level(arr.group("body")):
            ok, val = pg_default_to_json(part)
            if not ok:
                return False, None
            items.append(val)
        return True, items

    cast = re.match(r"^(?P<lit>.+?)::[A-Za-z_][\w \[\]\".]*$", e, re.DOTALL)
    if cast:
        e = cast.group("lit").strip()

    if re.fullmatch(r"NULL", e, re.IGNORECASE):
        return True, None
    if re.fullmatch(r"true|false", e, re.IGNORECASE):
        return True, e.lower() == "true"
    if re.fullmatch(r"-?\d+", e):
        return True, int(e)
    if re.fullmatch(r"-?\d*\.\d+", e):
        return True, float(e)
    if re.fullmatch(r"'([^']*)'", e, re.DOTALL):
        return True, e[1:-1]

    return False, None


#: `IF <ident> ... NOT IN ('a','b') THEN ... 22023 ... END IF;` — a REFUSAL.
_NOT_IN_GUARD = re.compile(
    r"IF\s+(?P<ident>[A-Za-z_]\w*)\b[^;]*?\bNOT\s+IN\s*\((?P<vals>[^)]*)\)\s*THEN"
    r"(?P<body>.*?)END\s+IF\s*;",
    re.IGNORECASE | re.DOTALL,
)
#: `    v_type  TEXT := NULLIF(lower(btrim(p_entity_type)), '');` -> v_type is p_entity_type.
#: Single-line by construction: `\s` would swallow the newline after DECLARE and
#: capture the keyword itself as the local.
_LOCAL_FROM_ARG = re.compile(
    r"^[ \t]*(?P<local>[A-Za-z_]\w*)[ \t]+[A-Za-z_][\w\[\] ]*?[ \t]*:=[^;\n]*?\b(?P<arg>p_[A-Za-z_]\w*)\b",
    re.IGNORECASE | re.MULTILINE,
)


def argument_enums(src: str, args: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Allowed values for the arguments the SQL actually REFUSES, read off `prosrc`.

    Introspected, never asserted — same rule as `refuses` / `tier_rows`. The
    `22023` requirement is the whole point: `p_freq` is matched by a bare
    `CASE … IN ('day','d','daily') … ELSE 'month' END` and raises nothing, so
    an unrecognised value silently yields MONTHLY data and a `200`. Publishing
    an enum there would promise a `400` the server never sends — exactly the
    confidently-wrong failure this contract exists to prevent. No raise, no enum.
    """
    names = {a["name"] for a in args}
    locals_to_arg = {
        m.group("local").lower(): m.group("arg").lower()
        for m in _LOCAL_FROM_ARG.finditer(src)
        if m.group("arg").lower() in names
    }

    found: dict[str, list[str]] = {}
    for m in _NOT_IN_GUARD.finditer(src):
        if "22023" not in m.group("body"):
            continue  # a filter, not a refusal
        ident = m.group("ident").lower()
        arg = ident if ident in names else locals_to_arg.get(ident)
        if not arg:
            continue
        vals = [v.strip()[1:-1] for v in split_top_level(m.group("vals")) if v.strip().startswith("'")]
        if vals:
            found.setdefault(arg, vals)
    return found


#: Values that are CANONICAL but not ENFORCED — suggestions, never constraints.
#: Kept as `examples` rather than `enum` on purpose: each of these arguments is a
#: filter or a fallback, so an unlisted value is accepted and simply matches
#: nothing (or falls back). `tests/test_openapi_spec.py` pins each list to the
#: values the SQL and the reference pages actually use.
SUGGESTED_VALUES: dict[str, list[str]] = {
    "p_freq": ["month", "day"],
    "p_scope": ["con", "ind"],
    "p_doc_type": ["itr", "dfp"],
}


def annotate_argument(schema: dict[str, Any], arg: dict[str, Any], enums: dict[str, list[str]]) -> dict[str, Any]:
    """Attach `default` / `enum` / `examples` to one argument's schema, in place."""
    name = arg["name"].lower()
    if arg.get("default") is not None:
        ok, value = pg_default_to_json(arg["default"])
        if ok:
            schema["default"] = value
    if name in enums:
        schema["enum"] = enums[name]
    elif name in SUGGESTED_VALUES:
        schema["examples"] = SUGGESTED_VALUES[name]
    return schema


def parse_result_columns(result: str) -> list[dict[str, str]] | None:
    """`TABLE(a text, b date)` -> [{name, type}]. None for a scalar return."""
    m = re.match(r"^\s*(?:SETOF\s+)?TABLE\s*\((?P<body>.*)\)\s*$", result, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    cols: list[dict[str, str]] = []
    for raw in split_top_level(m.group("body")):
        parts = raw.strip().split(None, 1)
        if len(parts) == 2:
            cols.append({"name": parts[0], "type": parts[1].strip()})
    return cols


_TIER_CASE = re.compile(
    r"CASE\s+(?:api\.caller_tier\(\)|v_tier)\s+"
    r"WHEN\s+'authenticated'\s+THEN\s+(?P<auth>\d+)\s+"
    r"ELSE\s+(?P<anon>\d+)\s+END",
    re.IGNORECASE,
)


def tier_ceilings(src: str) -> tuple[int, int] | None:
    """Read `CASE api.caller_tier() WHEN 'authenticated' THEN a ELSE b END`.

    Returns (anon, authenticated) for the first such CASE, or None. Only the
    row ceilings are shaped like this; `assert_panel_universe`'s 1/0 flag is
    handled by its caller, which knows it is a boolean, not a row count.
    """
    m = _TIER_CASE.search(src)
    if not m:
        return None
    return int(m.group("anon")), int(m.group("auth"))


def called_helpers(src: str, helper_names: set[str]) -> list[str]:
    return sorted(h for h in helper_names if f"api.{h}" in src)


# --------------------------------------------------------------------------
# Descriptions: the catalog's COMMENT, plus the behaviour we introspected.
# --------------------------------------------------------------------------


def describe_function(fn: dict[str, Any]) -> str:
    """COMMENT first (it is the contract's own prose), then the ceilings."""
    parts: list[str] = []
    if fn["comment"]:
        parts.append(fn["comment"].strip())

    if fn["refuses"]:
        note = (
            f"**Row cap.** A window producing more than {PAGE_SIZE} rows raises "
            f"SQLSTATE `22023` naming this function. Nothing is trimmed to fit — "
            f"PostgREST would silently cut the response at {PAGE_SIZE} and a "
            f"cut-short series is indistinguishable from one that simply ends."
        )
        if fn["paged"]:
            note += (
                f" This function pages: send `p_after = \"\"` for the first page, then "
                f"the key copied from the last row; a page shorter than {PAGE_SIZE} is "
                f"the last. `p_after = null` is whole-result mode, which is what refuses."
            )
        else:
            note += " This function does not page — narrow the window instead."
        parts.append(note)

    if fn["tier_rows"]:
        anon, auth = fn["tier_rows"]
        parts.append(
            f"**Tier ceiling.** Rows are CLAMPED, silently, to {anon} for anonymous "
            f"callers and {auth} for signed-in ones; a `p_limit` above the ceiling is "
            f"lowered to it rather than refused. This is the opposite of the "
            f"`22023` row cap the paging functions raise — here nothing tells you the "
            f"result was cut, so treat a result of exactly {anon} (or {auth}) rows as "
            f"probably truncated."
        )

    if fn["id_cap"]:
        anon, auth = fn["id_cap"]
        parts.append(
            f"**Id ceiling.** At most {anon} ids per call for anonymous callers and "
            f"{auth} for signed-in ones; more raises SQLSTATE `22023` naming the "
            f"limit. A panel is never silently trimmed to fit."
        )

    return "\n\n".join(parts)


def describe_view(name: str, comment: str | None) -> str:
    parts: list[str] = []
    if comment:
        parts.append(comment.strip())
    parts.append(
        f"**Paging.** A GET view pages normally with `limit`/`offset` (and `Range`). "
        f"Every response is cut at {PAGE_SIZE} rows server-side regardless of tier; "
        f"read `Content-Range` to detect it (`0-999/*` is a truncated page, and "
        f"`Prefer: count=exact` turns the `*` into the total)."
    )
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# Spec assembly
# --------------------------------------------------------------------------


def error_responses(has_22023: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "400": {
            "description": (
                "Bad request. Contract violations raise SQLSTATE `22023` with a "
                "message naming the limit or the argument at fault."
                if has_22023
                else "Bad request — a malformed filter or an unparseable argument."
            ),
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
        "401": {
            "description": (
                "No usable `apikey`, or a request for a schema outside `api`. "
                "`Accept-Profile: public` and any `cvm_*` / `b3_cotahist` / `cia_*` "
                "path answer 401 for every caller, by grant — schema `api` is the "
                "entire public surface."
            ),
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
        "404": {
            "description": "No such endpoint in schema `api`.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
        },
    }
    return out


# Functions whose rows are NOT oldest first. A register of documents is read
# newest delivery first (24_api_fnet.sql orders by delivered_at DESC), and the
# 200 description must not claim otherwise.
_ORDER: dict[str, str] = {
    "fund_documents": "newest delivery first",
    "fund_restatements": "newest delivery first",
    # 26_api_events_macro.sql orders a company's IPE filings newest first.
    "company_events": "newest delivery first",
}


def build_function_path(fn: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    enums = fn.get("enums") or {}
    for arg in fn["arguments"]:
        schema = dict(pg_type_to_schema(arg["type"]))
        if arg["default"] is None:
            required.append(arg["name"])
        else:
            schema["description"] = f"Defaults to `{arg['default']}`."
        props[arg["name"]] = annotate_argument(schema, arg, enums)

    body_schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        body_schema["required"] = required
    if not props:
        body_schema["description"] = "This function takes no arguments; send `{}`."

    cols = fn["result_columns"]
    if cols is None:
        ok_schema = pg_type_to_schema(fn["result"])
    else:
        row = {
            "type": "object",
            "properties": {c["name"]: pg_type_to_schema(c["type"]) for c in cols},
        }
        ok_schema = {"type": "array", "items": row}

    op: dict[str, Any] = {
        "operationId": f"rpc_{fn['name']}",
        "summary": fn["name"],
        "description": describe_function(fn),
        "tags": [fn["tag"]],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": body_schema}},
        },
        "responses": {
            "200": {
                "description": (
                    f"The result set, {_ORDER.get(fn['name'], 'oldest first')}. "
                    "An unknown id is an empty array, not a 404 and never a guessed value."
                    if cols is not None
                    else "The result."
                ),
                "content": {"application/json": {"schema": ok_schema}},
            },
            **error_responses(has_22023=True),
        },
    }
    return {"post": op}


_FILTER_HINT = (
    "PostgREST filter on `{col}` — `eq.`, `neq.`, `gt.`, `gte.`, `lt.`, `lte.`, "
    "`in.`, `is.` (e.g. `{col}=eq.<value>`)."
)


def build_view_path(name: str, comment: str | None, columns: list[dict[str, Any]], tag: str) -> dict[str, Any]:
    params: list[dict[str, Any]] = [
        {
            "name": "select",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "description": "Columns to return, comma separated. Omit for all of them.",
        },
        {
            "name": "order",
            "in": "query",
            "required": False,
            "schema": {"type": "string"},
            "description": "Sort, e.g. `trade_date.desc`. Always order a paged read, or `limit`/`offset` walk an undefined sequence.",
        },
        {
            "name": "limit",
            "in": "query",
            "required": False,
            "schema": {"type": "integer", "maximum": PAGE_SIZE},
            "description": f"Rows to return. The server cuts every response at {PAGE_SIZE} whatever you ask for.",
        },
        {
            "name": "offset",
            "in": "query",
            "required": False,
            "schema": {"type": "integer"},
            "description": "Rows to skip. Pairs with `limit` and `order` to page.",
        },
    ]
    for col in columns:
        params.append(
            {
                "name": col["name"],
                "in": "query",
                "required": False,
                "schema": {"type": "string"},
                "description": _FILTER_HINT.format(col=col["name"]),
            }
        )

    row = {
        "type": "object",
        "properties": {c["name"]: pg_type_to_schema(c["type"]) for c in columns},
    }

    op = {
        "operationId": f"get_{name}",
        "summary": name,
        "description": describe_view(name, comment),
        "tags": [tag],
        "parameters": params,
        "responses": {
            "200": {
                "description": "Matching rows.",
                "content": {"application/json": {"schema": {"type": "array", "items": row}}},
                "headers": {
                    "Content-Range": {
                        "description": f"`0-999/*` means the page was cut at {PAGE_SIZE}. Send `Prefer: count=exact` for the total.",
                        "schema": {"type": "string"},
                    }
                },
            },
            **error_responses(has_22023=False),
        },
    }
    return {"get": op}


# Which reference page an object belongs to. Read off the existing api-docs/
# nav so the generated sections land beside the prose that already covers them
# rather than in one undifferentiated list.
_TAGS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(quotes|equities|bdrs|units|fund_quotas|cash_securities|auctions)$"), "Quotes"),
    (re.compile(r"^quote_"), "Quotes"),
    (re.compile(r"^(option_|termo_)"), "Derivatives"),
    (re.compile(r"^(funds|fund_nav|fund_profile|search_funds)$"), "Funds"),
    (re.compile(r"^(fund_holdings|fund_debentures)$"), "Holdings"),
    (re.compile(r"^fidc_"), "FIDC"),
    (re.compile(r"^(fund_documents|fund_restatements)$"), "FNET documents"),
    (re.compile(r"^(financials|company_financials)$"), "Financials"),
    (re.compile(r"^anbima_"), "ANBIMA"),
    (re.compile(r"^inflation"), "Inflation"),
    (re.compile(r"^(macro_series|ptax)$"), "Macro"),
    (re.compile(r"^company_events$"), "Company events"),
    (re.compile(r"^screen_"), "Screens"),
    (re.compile(r"^(short_interest|short_interest_by_sector|investor_flow)$"), "Short interest & flows"),
    (re.compile(r"^lending_"), "Securities lending"),
    (re.compile(r"^panel$"), "Panel"),
    (re.compile(r"^(lookup)$"), "Lookup"),
    (re.compile(r"^(coverage|metric_coverage|catalog)$"), "Coverage & catalog"),
]


def tag_for(name: str) -> str:
    for pattern, tag in _TAGS:
        if pattern.search(name):
            return tag
    return "Other"


def build_spec(conn) -> dict[str, Any]:
    cur = conn.cursor()

    cur.execute(HELPERS_SQL)
    helper_src = {row[0]: row[1] or "" for row in cur.fetchall()}
    helper_names = set(helper_src)

    cur.execute(FUNCTIONS_SQL)
    functions: list[dict[str, Any]] = []
    for name, args, result, returns_set, comment, src, auth_granted in cur.fetchall():
        src = src or ""
        helpers = called_helpers(src, helper_names)
        helper_blob = "\n".join(helper_src[h] for h in helpers)

        id_cap = None
        if "assert_panel_ids" in helpers:
            id_cap = tier_ceilings(helper_src["assert_panel_ids"])

        functions.append(
            {
                "name": name,
                "arguments": parse_arguments(args or ""),
                "result": result,
                "result_columns": parse_result_columns(result) if returns_set else None,
                "comment": comment,
                "refuses": "assert_row_cap" in src,
                # src + helpers: `panel`'s p_entity_type guard lives in
                # api.assert_panel_universe, not in panel's own body.
                "enums": argument_enums(src + "\n" + helper_blob, parse_arguments(args or "")),
                "paged": any(a["name"] == "p_after" for a in parse_arguments(args or "")),
                "tier_rows": tier_ceilings(src),
                "id_cap": id_cap,
                "auth_granted": auth_granted,
                "tag": tag_for(name),
                "_helper_blob": helper_blob,
            }
        )

    cur.execute(VIEWS_SQL)
    views = [{"name": r[0], "comment": r[1]} for r in cur.fetchall()]
    granted_views = {v["name"] for v in views}

    cur.execute(COLUMNS_SQL)
    columns: dict[str, list[dict[str, Any]]] = {}
    for table, column, data_type, udt_name, _pos in cur.fetchall():
        if table not in granted_views:
            continue
        if data_type == "ARRAY":
            # information_schema spells an array's element type in udt_name
            # with a leading underscore (_text); pg_type_to_schema wants text[].
            data_type = f"{udt_name.lstrip('_')}[]"
        columns.setdefault(table, []).append({"name": column, "type": data_type})

    paths: dict[str, Any] = {}
    for view in views:
        paths[f"/{view['name']}"] = build_view_path(
            view["name"], view["comment"], columns.get(view["name"], []), tag_for(view["name"])
        )
    for fn in functions:
        paths[f"/rpc/{fn['name']}"] = build_function_path(fn)

    tags_used = sorted({tag_for(v["name"]) for v in views} | {f["tag"] for f in functions})

    spec = {
        "openapi": SPEC_VERSION,
        "info": {
            "title": "SILO Data API",
            "version": _contract_version(conn),
            "summary": "Read-only Brazilian public financial data: CVM filings, BACEN series, B3 quotes and the B3 BDI group.",
            "description": _INFO_DESCRIPTION,
            "license": {"name": "See repository", "url": "https://github.com/PedroDnT/SILO-BZ"},
        },
        "servers": [{"url": SERVER_URL, "description": "Supabase PostgREST, schema `api`"}],
        # ONE option, not two. OpenAPI's `security` is a list of ALTERNATIVES, so
        # [{apikey}, {apikey, bearerAuth}] is the idiomatic way to say "bearer is
        # optional" — apikey appears in both, so it is always required. Accurate,
        # and unreadable: a playground renders the two alternatives as a picker,
        # which invites "maybe I can skip the apikey". You never can.
        #
        # So the contract states the mandatory half only. `bearerAuth` stays
        # defined under securitySchemes (it is real, and it is what raises the
        # tier ceilings) and is documented on api-docs/conventions.mdx; it is
        # simply not offered as an alternative to the key.
        "security": [{"apikey": []}],
        "tags": [{"name": t} for t in tags_used],
        "paths": dict(sorted(paths.items())),
        "components": {
            "securitySchemes": {
                "apikey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "apikey",
                    "description": (
                        "The publishable key (`sb_publishable_…`), on every request. It is "
                        "NOT a JWT — sending it as `Authorization: Bearer` is rejected as an "
                        "invalid JWT. It identifies the project, not you, and maps to the "
                        "Postgres `anon` role."
                    ),
                },
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": (
                        "Optional. A user JWT from Supabase Auth (GitHub, at "
                        "https://silo-bz-deloslabs.vercel.app/signin.html), sent BESIDE `apikey`, "
                        "not instead of it. It maps to the `authenticated` role, which "
                        "raises the per-tier ceilings — it never widens the object set."
                    ),
                },
            },
            "parameters": {
                "AcceptProfile": {
                    "name": "Accept-Profile",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "enum": ["api"]},
                    "description": "Schema selector on GET. `api` is the only reachable schema; `public` answers 401.",
                },
                "ContentProfile": {
                    "name": "Content-Profile",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "enum": ["api"]},
                    "description": "Schema selector on POST (including `/rpc/`). `api` is the only reachable schema.",
                },
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "description": "PostgREST error body. `code` carries the SQLSTATE — `22023` is a contract refusal.",
                    "properties": {
                        "code": {"type": ["string", "null"], "examples": ["22023"]},
                        "message": {"type": ["string", "null"]},
                        "details": {"type": ["string", "null"]},
                        "hint": {"type": ["string", "null"]},
                    },
                }
            },
        },
    }
    return spec


_INFO_DESCRIPTION = """\
Schema `api` over PostgREST. Views are `GET /<view>`; functions are
`POST /rpc/<function>` with a JSON body.

**This document is generated** from the live Postgres catalog by
`scripts/gen_openapi.py` — `pg_get_function_arguments` for the RPC signatures,
`information_schema.columns` for the view columns, and the granted-to-`anon`
privilege set for which objects exist at all. It is not hand-maintained, and
`tests/test_openapi_spec.py` fails the build when it drifts from the SQL.

### Two different ceilings

Reading one for the other is the most expensive mistake on this API.

* **The row cap refuses.** Thirty-three set-returning functions raise SQLSTATE
  `22023` when the window they were handed would produce more than 1000 rows.
  Nothing is trimmed, and the error says why and how to fix it (the message,
  plus PostgREST's `details` and `hint`). Three of them (`panel`,
  `quote_history`, `fund_nav`) take a `p_after` cursor so you can walk the
  series; the other thirty ask you to narrow the window. `fund_nav` paging
  additionally REQUIRES `p_entity_type` — its cursor is a bare period, which
  is unique only within one family, and CNPJs that file under both `fi` and
  `fidc` in the same month would otherwise be ambiguous.
* **The tier ceiling clamps.** Five other functions (`search_funds`,
  `option_chain`, `option_exercises`, `fund_holdings`, `fund_debentures`)
  silently lower `p_limit` to a per-tier maximum. No error is raised, so the
  only way to know the result was cut is to know the ceiling. Signing in
  raises it.

Separately from both, PostgREST's server-wide `db-max-rows = 1000` cuts every
response, on every endpoint, for every tier. On the GET views `Content-Range`
is the signal (`0-999/*`); `Prefer: count=exact` turns the `*` into a total.

### Retention

Most of this warehouse is append-only history. The **B3 BDI group** —
`short_interest`, `short_interest_by_sector`, `investor_flow`,
`lending_trades`, `lending_participants` — is not: B3 keeps roughly 21 business
days and publishes no archive. A missed session cannot be bought back. See
Market Coverage.
"""


def _contract_version(conn) -> str:
    """The catalog's own version, so the spec is stamped with the contract it read.

    `api.catalog()` is a constant jsonb carrying CATALOG_VERSION; reading it
    keeps the spec's `info.version` pinned to the deployed contract instead of
    a number this script would otherwise have to invent.
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT (api.catalog() -> 'version')::text")
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0]).strip('"')
    except Exception:  # pragma: no cover - catalog() is present in every apply
        conn.rollback()
    return "0"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dsn",
        default=os.environ.get("POSTGRES_URL") or os.environ.get("SILO_API_DATABASE_URL"),
        help="Postgres connection string. Defaults to $POSTGRES_URL / $SILO_API_DATABASE_URL.",
    )
    args = ap.parse_args(argv)

    if not args.dsn:
        ap.error(
            "no DSN: set POSTGRES_URL (or SILO_API_DATABASE_URL), or pass --dsn. "
            "This script reads the live catalog; it has no offline mode on purpose."
        )

    with psycopg2.connect(args.dsn) as conn:
        spec = build_spec(conn)

    json.dump(spec, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
