"""One data-access interface for the engine: ``SiloClient.call(tool, args) -> rows``.

Implementations:

* ``McpClient`` (primary, owner's decision): JSON-RPC 2.0 ``tools/call`` against
  the read-only remote MCP ``silo-mcp``. Envelope as served by
  ``supabase/functions/silo-mcp/tools.ts``: a success is
  ``result.content[0].text`` = ``rows: n\\nprovenance: ...\\n[...]\\n<json>``
  (the JSON is the last line); a SILO refusal is ``result.isError = true`` with
  the PostgREST body verbatim in the text (SQLSTATE 22023 = the request crossed
  a stated ceiling). The response may be plain JSON or one SSE ``data:`` event.
* ``PostgrestClient`` (fallback): ``POST /rest/v1/rpc/<fn>`` (views: ``GET
  /rest/v1/<view>``) with ``Accept-Profile: api``.
* ``FakeClient`` (tests and ``--client fake``): canned rows matched on args.

All three: no retry, no trimming, and every request is appended to
``provenance`` (tool, args, UTC timestamp, row count, verbatim error). Only the
public publishable key is ever sent, as ``apikey`` (never as a Bearer token,
never a secret key).
"""

from __future__ import annotations

import abc
import copy
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_MCP_URL = "https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/silo-mcp"
DEFAULT_REST_URL = "https://zcjbtpxuhdekpwcxmepn.supabase.co/rest/v1"
# Public by design: printed in skill.md and shipped in sdk/silo_client.
DEFAULT_PUBLISHABLE_KEY = "sb_publishable__yfFQsykAglrvc9GS6_PYw_B24ex437"
MCP_PROTOCOL_VERSION = "2025-06-18"

# The contract's GET views (tools.ts, "Views"); every other tool is an RPC.
VIEW_TOOLS = frozenset(
    {
        "funds",
        "quotes",
        "equities",
        "bdrs",
        "units",
        "fund_quotas",
        "cash_securities",
        "auctions",
        "short_interest",
        "short_interest_by_sector",
        "lending_trades",
        "lending_participants",
        "investor_flow",
    }
)

Clock = Callable[[], dt.datetime]
# (url, method, body bytes or None, headers, timeout) -> (status, text)
Transport = Callable[[str, str, "bytes | None", dict, float], "tuple[int, str]"]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ToolError(Exception):
    """A tool call that returned no rows: refusal, HTTP error, network error. ``verbatim`` is the source text."""

    def __init__(self, tool: str, verbatim: str, sqlstate: str | None = None):
        self.tool = tool
        self.verbatim = verbatim
        self.sqlstate = sqlstate if sqlstate is not None else _sqlstate(verbatim)
        super().__init__(f"{tool}: {verbatim}")


def _sqlstate(text: str) -> str | None:
    m = re.search(r'"code"\s*:\s*"([0-9A-Z]{5}|PGRST\d+)"', text or "")
    return m.group(1) if m else None


@dataclass
class ProvenanceEntry:
    call_id: int
    tool: str
    args: dict
    requested_at_utc: str
    row_count: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool": self.tool,
            "args": self.args,
            "requested_at_utc": self.requested_at_utc,
            "row_count": self.row_count,
            "error": self.error,
        }


def _iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SiloClient(abc.ABC):
    """``call`` records provenance, then delegates to ``_request``."""

    kind = "abstract"

    def __init__(self, clock: Clock | None = None):
        self._clock = clock or utc_now
        self.provenance: list[ProvenanceEntry] = []

    @property
    def last_call_id(self) -> int | None:
        return self.provenance[-1].call_id if self.provenance else None

    def call(self, tool: str, args: dict | None = None) -> list[dict]:
        args = copy.deepcopy(args or {})
        entry = ProvenanceEntry(
            call_id=len(self.provenance) + 1,
            tool=tool,
            args=args,
            requested_at_utc=_iso(self._clock()),
        )
        self.provenance.append(entry)
        try:
            rows = self._request(tool, copy.deepcopy(args))
        except ToolError as exc:
            entry.error = exc.verbatim
            raise
        except (OSError, ValueError) as exc:
            # Network or decoding failure: recorded verbatim and re-raised as a
            # ToolError so the section that asked becomes unknown, never empty.
            entry.error = f"{type(exc).__name__}: {exc}"
            raise ToolError(tool, entry.error) from exc
        entry.row_count = len(rows)
        return rows

    @abc.abstractmethod
    def _request(self, tool: str, args: dict) -> list[dict]: ...


def _urllib_transport(url: str, method: str, body: bytes | None, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URL)
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _rows_from_payload(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


class McpClient(SiloClient):
    """JSON-RPC 2.0 client for silo-mcp (streamable HTTP, stateless)."""

    kind = "mcp"

    def __init__(
        self,
        url: str = DEFAULT_MCP_URL,
        api_key: str = DEFAULT_PUBLISHABLE_KEY,
        *,
        transport: Transport | None = None,
        timeout: float = 120.0,
        clock: Clock | None = None,
    ):
        super().__init__(clock)
        if api_key.startswith("sb_secret_"):
            raise ValueError("refusing a secret key: only the public publishable key is allowed")
        self.url = url
        self._key = api_key
        self._transport = transport or _urllib_transport
        self._timeout = timeout
        self._next_id = 0

    def _request(self, tool: str, args: dict) -> list[dict]:
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
            "apikey": self._key,
        }
        status, text = self._transport(self.url, "POST", json.dumps(body).encode("utf-8"), headers, self._timeout)
        if status != 200:
            raise ToolError(tool, f"MCP HTTP {status}: {text}")
        msg = parse_mcp_message(text)
        if "error" in msg:
            raise ToolError(tool, f"MCP JSON-RPC error: {json.dumps(msg['error'], ensure_ascii=False)}")
        result = msg.get("result") or {}
        content = result.get("content") or []
        out_text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        if result.get("isError"):
            raise ToolError(tool, out_text)
        # "rows: n\nprovenance: ...\n[...lines]\n<json>": the JSON is the last line.
        last = out_text.rsplit("\n", 1)[-1]
        return _rows_from_payload(json.loads(last))


def parse_mcp_message(text: str) -> dict:
    """A JSON-RPC message from a plain JSON body or an SSE stream (``data:`` lines)."""
    t = text.lstrip()
    if t.startswith("{"):
        return json.loads(t)
    payload = "".join(line[5:].strip() for line in t.splitlines() if line.startswith("data:"))
    if not payload:
        raise ValueError("MCP response carried no JSON-RPC message")
    return json.loads(payload)


class PostgrestClient(SiloClient):
    """Fallback: schema ``api`` over PostgREST with the publishable key."""

    kind = "postgrest"

    def __init__(
        self,
        rest_url: str = DEFAULT_REST_URL,
        api_key: str = DEFAULT_PUBLISHABLE_KEY,
        *,
        transport: Transport | None = None,
        timeout: float = 120.0,
        clock: Clock | None = None,
    ):
        super().__init__(clock)
        if api_key.startswith("sb_secret_"):
            raise ValueError("refusing a secret key: only the public publishable key is allowed")
        self.rest_url = rest_url.rstrip("/")
        self._key = api_key
        self._transport = transport or _urllib_transport
        self._timeout = timeout

    def _request(self, tool: str, args: dict) -> list[dict]:
        headers = {"apikey": self._key, "Accept": "application/json", "Accept-Profile": "api"}
        if tool in VIEW_TOOLS:
            # Same argument shape as the MCP view tools: filters, select, order, limit, offset.
            query: list[tuple[str, str]] = []
            for col, expr in (args.get("filters") or {}).items():
                query.append((col, str(expr)))
            for key in ("select", "order", "limit", "offset"):
                if key in args and args[key] is not None:
                    query.append((key, str(args[key])))
            qs = urllib.parse.urlencode(query)
            url = f"{self.rest_url}/{tool}" + (f"?{qs}" if qs else "")
            status, text = self._transport(url, "GET", None, headers, self._timeout)
        else:
            url = f"{self.rest_url}/rpc/{tool}"
            headers = {**headers, "Content-Profile": "api", "Content-Type": "application/json"}
            status, text = self._transport(url, "POST", json.dumps(args).encode("utf-8"), headers, self._timeout)
        if status >= 400:
            raise ToolError(tool, f"PostgREST HTTP {status}: {text}")
        return _rows_from_payload(json.loads(text) if text else None)


class FakeClient(SiloClient):
    """Canned rows: ``{tool: [{"match": {...}, "rows": [...]} | {"match": {...}, "error": "..."}]}``.

    The first entry whose ``match`` is a subset of the call's args answers it.
    A call nothing matches raises a ToolError, as an unknown tool would.
    """

    kind = "fake"

    def __init__(self, canned: dict[str, list[dict]], clock: Clock | None = None):
        super().__init__(clock)
        self._canned = canned

    def _request(self, tool: str, args: dict) -> list[dict]:
        for entry in self._canned.get(tool, []):
            match = entry.get("match") or {}
            if all(k in args and _same(args[k], v) for k, v in match.items()):
                if "error" in entry:
                    raise ToolError(tool, entry["error"])
                return copy.deepcopy(entry.get("rows", []))
        raise ToolError(tool, f"FakeClient: no canned answer for {tool} with args {json.dumps(args, sort_keys=True)}")


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def load_fake_rows(path: str | Path) -> dict[str, list[dict]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}
