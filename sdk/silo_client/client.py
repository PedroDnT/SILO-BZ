"""The client. One class, PostgREST underneath, no magic.

Every method maps 1:1 onto a published endpoint (schema `api` on the Supabase
Data API). Views are GET resources; functions are POST /rpc/<name>. The
catalog is fetched once per client and drives metric validation.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Union

import httpx

Datish = Union[str, date, None]


#: PostgREST's `db-max-rows`. It is a SERVER-WIDE setting, identical for every
#: caller and every tier — signing in raises ids, page sizes and the statement
#: timeout, never this. A response of exactly this many rows is therefore
#: indistinguishable from a truncated one unless the server tells us the total.
SERVER_ROW_CAP = 1000


class SiloError(RuntimeError):
    """An API-level failure. Carries the HTTP status and the server's body —
    the server's error text (e.g. option_chain's required-prefix message) is
    the useful part, so it is never swallowed."""

    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")


class SiloTruncated(SiloError):
    """The server returned fewer rows than exist, and said so.

    THIS IS THE DEFECT THE SDK EXISTS TO PREVENT. PostgREST caps every response
    at `db-max-rows` (1000) and answers HTTP 200 with the first page, oldest
    first. A caller asking for six years of daily quotes gets three and a half
    years and no indication of it — the series just appears to end. Range paging
    does not work on RPC calls, so the SDK cannot silently stitch the rest;
    raising is the only honest answer.
    """

    def __init__(self, returned: int, total: Optional[int], url: str):
        self.returned = returned
        self.total = total
        of = f"of {total:,}" if total is not None else "of an unknown total"
        super().__init__(
            206,
            f"the server returned {returned:,} rows {of} and stopped at its "
            f"{SERVER_ROW_CAP}-row cap. Narrow the window (start/end), ask for "
            f"fewer ids, or request one metric at a time. Paging does not work "
            f"on this endpoint.",
            url,
        )


class SiloTimeout(SiloError):
    """SQLSTATE 57014 — the query ran out of the server's time budget.

    The budget is per-role (3s anonymous, 8s signed in) and the caller cannot
    raise it, so the message names what they CAN change.
    """

    def __init__(self, body: str, url: str):
        super().__init__(
            504,
            "the query exceeded the server's time budget. Narrow the window, "
            "ask for fewer ids, or request fewer metrics per call. Signing in "
            f"raises the budget from 3s to 8s. Server said: {body[:200]}",
            url,
        )


def _iso(d: Datish) -> Optional[str]:
    if d is None:
        return None
    return d.isoformat() if isinstance(d, date) else str(d)


class SiloClient:
    """Thin client for the Silo read API.

    Args:
        url:  Supabase project base (https://<ref>.supabase.co). Defaults to
              the SILO_URL environment variable.
        key:  publishable (anon) key. Defaults to SILO_ANON_KEY. The shared
              key printed in the docs is TESTING ONLY.
        transport: optional httpx transport (tests inject a MockTransport).
    """

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        retries: int = 2,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        base = (url or os.environ.get("SILO_URL", "")).rstrip("/")
        if not base:
            raise ValueError("url is required (or set SILO_URL)")
        self._key = key or os.environ.get("SILO_ANON_KEY", "")
        if not self._key:
            raise ValueError("key is required (or set SILO_ANON_KEY)")
        self._token = token or os.environ.get("SILO_TOKEN") or None
        self._rest = f"{base}/rest/v1"

        headers = {
            "apikey": self._key,
            "Accept": "application/json",
            # Ask the server for the true row count so a capped response can be
            # told apart from a complete one. Without it a 1000-row answer and a
            # 1,000,000-row answer look identical.
            "Prefer": "count=exact",
        }
        if self._token:
            # The publishable key identifies the PROJECT; the bearer token
            # identifies the CALLER. Sending it moves the request from the anon
            # role to authenticated, which raises the panel id ceiling from 3 to
            # 50, search_funds from 25 to 200, option_chain from 200 to 2000 and
            # the statement timeout from 3s to 8s. It does NOT raise the
            # server-wide 1000-row cap.
            headers["Authorization"] = f"Bearer {self._token}"

        if transport is None and retries:
            # Connection-level retries only. A retried POST is safe here because
            # every endpoint is read-only; httpx retries connect failures, never
            # a response the server already sent.
            transport = httpx.HTTPTransport(retries=retries)

        self._http = httpx.Client(timeout=timeout, transport=transport, headers=headers)
        self._catalog: Optional[Dict[str, Any]] = None

    @property
    def tier(self) -> str:
        """'authenticated' when a caller token is set, else 'anon'.

        Mirrors api.caller_tier() so client code can size its own requests
        instead of discovering a ceiling by hitting it.
        """
        return "authenticated" if self._token else "anon"

    # -- plumbing -----------------------------------------------------------

    @staticmethod
    def _total_from_content_range(value: Optional[str]) -> Optional[int]:
        """Parse PostgREST's `Content-Range: 0-999/12345` -> 12345.

        The total is `*` when the server was not asked to count, and the header
        is absent entirely on some responses; both mean "unknown", not "none".
        """
        if not value or "/" not in value:
            return None
        total = value.rsplit("/", 1)[1].strip()
        return int(total) if total.isdigit() else None

    def _check(self, r: httpx.Response, url: str) -> Any:
        """Turn a response into rows, or into the most useful exception.

        Truncation is checked BEFORE the rows are handed back, because a
        truncated series is not a smaller answer — it is a wrong one, and it
        looks exactly like a company that stopped trading.
        """
        if r.status_code >= 400:
            body = r.text
            # PostgREST surfaces the SQLSTATE in the body; 57014 is the
            # statement timeout and needs its own advice, not a generic 500.
            if "57014" in body or "canceling statement due to statement timeout" in body:
                raise SiloTimeout(body, url)
            raise SiloError(r.status_code, body, url)

        payload = r.json()
        if isinstance(payload, list):
            total = self._total_from_content_range(r.headers.get("Content-Range"))
            n = len(payload)
            if total is not None and total > n:
                raise SiloTruncated(n, total, url)
            if total is None and n >= SERVER_ROW_CAP:
                # No count came back and we are sitting exactly on the cap.
                # Cannot prove completeness, so do not imply it.
                raise SiloTruncated(n, None, url)
        return payload

    def _get(self, resource: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self._rest}/{resource}"
        r = self._http.get(url, params={k: v for k, v in params.items() if v is not None})
        return self._check(r, url)

    def _rpc(self, fn: str, body: Dict[str, Any]) -> Any:
        url = f"{self._rest}/rpc/{fn}"
        r = self._http.post(url, json={k: v for k, v in body.items() if v is not None})
        return self._check(r, url)

    # -- discovery ----------------------------------------------------------

    def catalog(self, refresh: bool = False) -> Dict[str, Any]:
        """The metric map + constraints. Cached; the server tells you the rules."""
        if self._catalog is None or refresh:
            self._catalog = self._rpc("catalog", {})
        return self._catalog

    def metrics(self) -> List[str]:
        return sorted(self.catalog()["metrics"].keys())

    def coverage(self) -> List[Dict[str, Any]]:
        """Per-dataset freshness (`as_of`) and honesty bound (`complete_through`)."""
        return self._rpc("coverage", {})

    def lookup(self, query: str) -> List[Dict[str, Any]]:
        """Resolve ticker/ISIN/CNPJ/name. Company rows carry a `tickers` array
        from CVM's published FCA map — never a name match."""
        return self._rpc("lookup", {"p_query": query})

    # -- series -------------------------------------------------------------

    def quote_history(
        self, ticker: str, start: Datish = None, end: Datish = None,
        board: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self._rpc("quote_history", {
            "p_ticker": ticker, "p_from": _iso(start), "p_to": _iso(end),
            "p_board": board,
        })

    def fund_nav(
        self, cnpj: str, start: Datish = None, end: Datish = None,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Monthly fundamentals. `end=None` = the honest window (only complete
        periods); pass an explicit end to see partial months verbatim."""
        return self._rpc("fund_nav", {
            "p_cnpj": cnpj, "p_from": _iso(start), "p_to": _iso(end),
            "p_entity_type": entity_type,
        })

    def option_chain(self, prefix: str, trade_date: Datish = None,
                     expiry_from: Datish = None,
                     limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """One underlying's option chain.

        `limit=None` uses the server's own default (100). The server clamps by
        tier — 200 anonymous, 2000 signed in — so a larger value is reduced
        rather than refused.
        """
        return self._rpc("option_chain", {
            "p_prefix": prefix, "p_trade_date": _iso(trade_date),
            "p_expiry_from": _iso(expiry_from), "p_limit": limit,
        })

    def quote_latest(self, ticker: str, board: Optional[str] = None) -> List[Dict[str, Any]]:
        """The most recent session for one instrument."""
        return self._rpc("quote_latest", {"p_ticker": ticker, "p_board": board})

    def option_history(self, codneg: str, start: Datish = None,
                       end: Datish = None) -> List[Dict[str, Any]]:
        """One option contract's own price history, by its B3 code."""
        return self._rpc("option_history", {
            "p_codneg": codneg, "p_from": _iso(start), "p_to": _iso(end),
        })

    def option_exercises(self, prefix: str, start: Datish = None,
                         end: Datish = None,
                         limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Recorded option exercise events (tpmerc 012 call / 013 put).

        `prefix` is a codneg prefix of at least three characters (e.g. "PETR")
        and is REQUIRED — the server raises 22023 without one, since an
        unprefixed scan of every exercise ever printed is the slowest query on
        the API. Checked here so the round trip is not spent on a knowable
        error.

        These are events, not quotes: one print per series, with no return
        semantics. Rows are clamped to 500 anonymous / 5000 signed in.
        """
        if len((prefix or "").strip()) < 3:
            raise ValueError(
                "option_exercises needs a codneg prefix of at least 3 "
                f"characters (e.g. 'PETR'); got {prefix!r}"
            )
        return self._rpc("option_exercises", {
            "p_prefix": prefix.strip().upper(), "p_from": _iso(start),
            "p_to": _iso(end), "p_limit": limit,
        })

    def termo_history(self, codneg: str, start: Datish = None,
                      end: Datish = None) -> List[Dict[str, Any]]:
        """Forward (termo) contract history, keyed on codneg and term days."""
        return self._rpc("termo_history", {
            "p_codneg": codneg, "p_from": _iso(start), "p_to": _iso(end),
        })

    def fund_profile(self, cnpj: str) -> List[Dict[str, Any]]:
        """Registry facts for one fund: name, family, administrator, manager."""
        return self._rpc("fund_profile", {"p_cnpj": cnpj})

    def search_funds(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Name search over the fund universe.

        The server clamps `limit` by tier — 25 anonymous, 200 signed in — so a
        larger value is silently reduced rather than refused. Check `.tier` if
        you need to know which ceiling you are under.
        """
        return self._rpc("search_funds", {"p_query": query, "p_limit": limit})

    def fund_holdings(self, cnpj: Optional[str] = None, ticker: Optional[str] = None,
                      start: Datish = None, end: Datish = None,
                      kind: str = "equity",
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """What a fund holds, or which funds hold a ticker.

        Exactly one of `cnpj` or `ticker`. This is the only edge in the
        warehouse joining the fund universe to the quote tape: CDA block 4
        publishes the B3 ticker a fund holds, block 2 the CNPJ of a held fund.

            silo.fund_holdings(ticker="PETR4")          # who holds it
            silo.fund_holdings(cnpj="05754060000113")   # what it holds
            silo.fund_holdings(cnpj=..., kind="fund")   # held FUNDS, not shares

        Rows are as filed — one per (application type, trading intent), never
        summed across them.
        """
        if (cnpj is None) == (ticker is None):
            raise ValueError(
                "fund_holdings needs exactly one of cnpj (what this fund holds) "
                "or ticker (which funds hold this ticker)"
            )
        return self._rpc("fund_holdings", {
            "p_cnpj": cnpj, "p_ticker": ticker,
            "p_from": _iso(start), "p_to": _iso(end),
            "p_kind": kind, "p_limit": limit,
        })

    # -- typed views (GET resources, not functions) --------------------------

    #: The eight published views. PostgREST serves these as filterable
    #: resources, so they take horizontal filters (`cd_ativo=eq.PETR4`) and
    #: `select`/`order`/`limit` rather than positional arguments.
    VIEWS = (
        "quotes", "equities", "bdrs", "units", "fund_quotas",
        "cash_securities", "auctions", "funds",
    )

    def view(self, name: str, **filters: Any) -> List[Dict[str, Any]]:
        """Read one of the typed views.

            client.view("equities", cd_ativo="eq.PETR4", limit=10)

        Filter syntax is PostgREST's own, passed through verbatim — the SDK
        does not invent a query language over it.
        """
        if name not in self.VIEWS:
            raise ValueError(f"unknown view {name!r}; served views are {list(self.VIEWS)}")
        return self._get(name, filters)

    # -- the primitive ------------------------------------------------------

    def panel(
        self,
        ids: Sequence[str],
        metrics: Sequence[str] = ("close", "nav"),
        start: Datish = None,
        end: Datish = None,
        freq: str = "month",
        wide: bool = True,
    ):
        """The (id, date, metric, value) panel — the API's one primitive.

        Metric names are validated against the live catalog so a typo fails
        HERE, loudly, instead of returning an empty panel that looks like
        missing data. `end=None` keeps the server's honest window for fund
        metrics. wide=True pivots to a DataFrame with (date) index and
        (id, metric) columns; missing observations stay NaN — never filled.
        """
        known = set(self.catalog()["metrics"].keys())
        bad = [m for m in metrics if m not in known]
        if bad:
            raise ValueError(
                f"unknown metric(s) {bad}; the catalog serves {sorted(known)}"
            )
        rows = self._rpc("panel", {
            "p_ids": list(ids), "p_metrics": list(metrics),
            "p_from": _iso(start), "p_to": _iso(end), "p_freq": freq,
        })
        if not wide:
            return rows
        try:
            import pandas as pd  # deferred: long-format callers never pay for it
        except ImportError as exc:  # pragma: no cover - exercised by hand
            raise ImportError(
                "panel(wide=True) needs pandas, which is an optional extra. "
                "Install it with `pip install silo-client[pandas]`, or call "
                "panel(..., wide=False) for the long (id, date, metric, value) "
                "rows this pivots."
            ) from exc

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.pivot_table(
            index="date", columns=["id", "metric"], values="value",
            aggfunc="first",  # the grain is unique; never averages anything
        ).sort_index()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SiloClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
