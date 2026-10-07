"""The schema `api` endpoint manifest, read offline from the analytical SQL.

One parser for the facts every contract test used to re-derive with its own
regex: which `api.*` functions and views exist, which are granted to the public
tiers, what parameters each function declares, and how each behaves above one
1000-row page (refuses via `api.assert_row_cap`, pages with a `p_after` cursor,
branches on `api.caller_tier()`).

No database. It parses `src/store/analytical/NN_*.sql` in the order
`scripts/apply_analytical.sh` applies them, so a later `CREATE OR REPLACE` of
the same name is the shipped definition. It reports what the SQL DOES; what the
contract INTENDS stays declared by hand in `serve/catalog.py` (`LIMITS["page"]`)
and `tests/test_endpoint_manifest.py` pins the two against each other.

Nothing at serve time imports this module: `catalog_payload()` is built from the
declared intent, never from a parse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"

# The files apply_analytical.sh runs, in its order. smoke.sql is not one.
SQL_GLOB = "[0-9][0-9]_*.sql"

# The two tiers that make an object PUBLIC. `silo_api` is the serve/ role and
# `service_role` bypasses the boundary; a grant to those alone publishes nothing.
PUBLIC_ROLES = ("anon", "authenticated")


def sql_files() -> List[Path]:
    return sorted(ANALYTICAL.glob(SQL_GLOB))


def strip_comments(sql: str) -> str:
    """Drop `--` line comments and /* */ blocks so prose never matches."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


_FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+api\.(?P<name>[a-z_][a-z0-9_]*)\s*"
    r"\((?P<args>.*?)\)\s*\n\s*RETURNS",
    re.IGNORECASE | re.DOTALL,
)
_VIEW = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+api\.(?P<name>[a-z_][a-z0-9_]*)\b",
    re.IGNORECASE,
)
_PARAM = re.compile(r"(?:^|,)\s*(p_[a-z0-9_]+)\s", re.IGNORECASE)
_BODY_OPEN = re.compile(r"\bAS\s+(\$[a-z_]*\$)", re.IGNORECASE)
_GRANT_SELECT = re.compile(
    r"\bGRANT\s+SELECT\s+ON\s+(?P<objects>.+?)\s+TO\s+(?P<grantees>[^;]+);",
    re.IGNORECASE | re.DOTALL,
)
_GRANT_EXECUTE = re.compile(
    r"\bGRANT\s+EXECUTE\s+ON\s+FUNCTION\s+(?P<objects>.+?)\s+TO\s+(?P<grantees>[^;]+);",
    re.IGNORECASE | re.DOTALL,
)
_API_RELATION = re.compile(r"\bapi\.(?P<name>[a-z_][a-z0-9_]*)\b", re.IGNORECASE)
_API_FUNCTION = re.compile(r"\bapi\.(?P<name>[a-z_][a-z0-9_]*)\s*\(", re.IGNORECASE)
_ASSERT_ROW_CAP = re.compile(r"\bapi\.assert_row_cap\s*\(", re.IGNORECASE)
_CALLER_TIER = re.compile(r"\bapi\.caller_tier\s*\(\s*\)", re.IGNORECASE)


@dataclass(frozen=True)
class Endpoint:
    """One object in schema `api`, as the SQL defines it."""

    name: str
    kind: str  # "rpc" or "view"
    file: str  # the analytical file whose definition ships
    params: Tuple[str, ...] = ()  # declared argument names, in order (rpc only)
    granted: bool = False  # EXECUTE / SELECT granted to anon or authenticated
    refuses: bool = False  # calls api.assert_row_cap: 22023 above one page
    calls_caller_tier: bool = False  # branches on api.caller_tier()

    @property
    def pages(self) -> bool:
        """Refuses above a page AND takes the p_after cursor to walk past it."""
        return self.refuses and "p_after" in self.params

    @property
    def raise_only(self) -> bool:
        """Refuses above a page and offers no cursor: narrow, never walk."""
        return self.refuses and "p_after" not in self.params

    @property
    def tier_clamps(self) -> bool:
        """Branches on the caller's tier without refusing: a silent ceiling."""
        return self.calls_caller_tier and not self.refuses


def _is_public(grantees: str) -> bool:
    names = {g.strip().strip('"').lower() for g in grantees.split(",")}
    return bool(names & set(PUBLIC_ROLES))


def _dollar_body(sql: str, start: int) -> str:
    """The dollar-quoted body of the function whose RETURNS clause ends near
    `start`; empty when there is none (a LANGUAGE sql one-liner still has one)."""
    m = _BODY_OPEN.search(sql, start)
    if not m:
        return ""
    tag = m.group(1)
    end = sql.find(tag, m.end())
    return sql[m.end(): end if end >= 0 else len(sql)]


def _granted(sql: str) -> Tuple[set, set]:
    views: set = set()
    functions: set = set()
    for m in _GRANT_SELECT.finditer(sql):
        if _is_public(m.group("grantees")):
            views.update(r.group("name").lower() for r in _API_RELATION.finditer(m.group("objects")))
    for m in _GRANT_EXECUTE.finditer(sql):
        if _is_public(m.group("grantees")):
            functions.update(f.group("name").lower() for f in _API_FUNCTION.finditer(m.group("objects")))
    return views, functions


@lru_cache(maxsize=1)
def _grants() -> Tuple[frozenset, frozenset]:
    views: set = set()
    functions: set = set()
    for path in sql_files():
        v, f = _granted(strip_comments(path.read_text(encoding="utf-8")))
        views |= v
        functions |= f
    return frozenset(views), frozenset(functions)


def granted_views() -> frozenset:
    """Every api relation SELECT-granted to anon or authenticated, by name."""
    return _grants()[0]


def granted_functions() -> frozenset:
    """Every api function EXECUTE-granted to anon or authenticated, by name."""
    return _grants()[1]


@lru_cache(maxsize=1)
def manifest() -> Dict[str, Endpoint]:
    """{name: Endpoint} for every function and view in schema `api`, helpers
    included (they are simply not `granted`)."""
    found: Dict[str, dict] = {}
    for path in sql_files():
        sql = strip_comments(path.read_text(encoding="utf-8"))
        for m in _FUNCTION.finditer(sql):
            body = _dollar_body(sql, m.end())
            found[m.group("name").lower()] = {
                "kind": "rpc",
                "file": path.name,
                "params": tuple(p.lower() for p in _PARAM.findall(m.group("args"))),
                "refuses": bool(_ASSERT_ROW_CAP.search(body)),
                "calls_caller_tier": bool(_CALLER_TIER.search(body)),
            }
        for m in _VIEW.finditer(sql):
            found[m.group("name").lower()] = {"kind": "view", "file": path.name}
    views, functions = _grants()
    return {
        name: Endpoint(
            name=name,
            granted=name in (functions if facts["kind"] == "rpc" else views),
            **facts,
        )
        for name, facts in found.items()
    }


def function_chunks(path: Path) -> Dict[str, str]:
    """{'api.<name>': raw text} for one file: each CREATE [OR REPLACE] FUNCTION
    api.* up to the next one (or end of file), comments kept, so a test can
    assert on a function's header, body and the statements that follow it."""
    sql = path.read_text(encoding="utf-8")
    pattern = re.compile(r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(api\.\w+)", re.I)
    starts = [(m.start(), m.group(1).lower()) for m in pattern.finditer(sql)]
    out: Dict[str, str] = {}
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(sql)
        out[name] = sql[pos:end]
    return out
