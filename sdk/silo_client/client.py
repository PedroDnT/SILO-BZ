"""The client. One class, PostgREST underneath, no magic.

Every method maps 1:1 onto a published endpoint (schema `api` on the Supabase
Data API). Views are GET resources; functions are POST /rpc/<name>. The
catalog is fetched once per client and drives metric validation.
"""

from __future__ import annotations

import os
import warnings
from datetime import date
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

import httpx

Datish = Union[str, date, None]


#: PostgREST's `db-max-rows`. It is a SERVER-WIDE setting, identical for every
#: caller and every tier — signing in raises ids, page sizes and the statement
#: timeout, never this. A response of exactly this many rows is therefore
#: indistinguishable from a truncated one unless the server tells us the total.
SERVER_ROW_CAP = 1000

#: The catalog version this client was written against (serve/catalog.py
#: CATALOG_VERSION). The server's catalog() carries its own; when the two
#: differ the client warns once — a newer server has endpoints, metrics or
#: limits this client does not know, an older one lacks some this client
#: wraps. Neither is an error, both are worth knowing before a long run.
KNOWN_CATALOG_VERSION = 26


class SiloCatalogDrift(UserWarning):
    """The server's catalog version is not the one this client was built for."""


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

    def __init__(self, returned: int, total: Optional[int], url: str,
                 rows: Optional[List[Dict[str, Any]]] = None):
        self.returned = returned
        self.total = total
        #: The partial page the server did send. Inspectable — to see where the
        #: cut fell, or which ids made it — and never to be treated as the
        #: series: it is the oldest `returned` rows of `total`, nothing more.
        self.rows: List[Dict[str, Any]] = rows if rows is not None else []
        of = f"of {total:,}" if total is not None else "of an unknown total"
        super().__init__(
            206,
            f"the server returned {returned:,} rows {of} and stopped at its "
            f"{SERVER_ROW_CAP}-row cap. Narrow the window (start/end), ask for "
            f"fewer ids, or request one metric at a time. Paging does not work "
            f"on this endpoint. The partial rows are on .rows.",
            url,
        )


class SiloOverCap(SiloError):
    """The server REFUSED a function call whose result would exceed the
    1000-row page (SQLSTATE 22023) rather than trim it. Not a bug: page it or
    narrow the window, ids or metrics.

    Three functions page: panel (`iter_panel`/`panel_all`), quote_history
    (`iter_quote_history`/`quote_history_all`) and fund_nav
    (`iter_fund_nav`/`fund_nav_all`, which need an `entity_type`). The rest —
    option_history, termo_history, financials, company_financials,
    anbima_classes — have no cursor: narrow the window instead."""

    def __init__(self, body: str, url: str) -> None:
        super().__init__(400, body, url)
        self.hint = (
            "the result is larger than one 1000-row page; page it with "
            "p_after via iter_panel()/iter_quote_history()/iter_fund_nav(), "
            "or narrow the request"
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

    def _check(self, r: httpx.Response, url: str,
               page: bool = False) -> Tuple[Any, Optional[int]]:
        """Turn a response into (rows, total), or into the most useful exception.

        Truncation is checked BEFORE the rows are handed back, because a
        truncated series is not a smaller answer — it is a wrong one, and it
        looks exactly like a company that stopped trading.

        `page=True` is the one exception, and it is a narrow one: the caller
        asked a VIEW for an explicit limit/offset, so a total larger than the
        page is the paging contract working, not the cap firing. RPC calls
        never pass it — Range paging does not work there, so on a function a
        short answer is always a wrong one.
        """
        if r.status_code >= 400:
            body = r.text
            # PostgREST surfaces the SQLSTATE in the body; 57014 is the
            # statement timeout and needs its own advice, not a generic 500.
            if "57014" in body or "canceling statement due to statement timeout" in body:
                raise SiloTimeout(body, url)
            if "22023" in body and "more than 1000 rows" in body:
                raise SiloOverCap(body, url)
            raise SiloError(r.status_code, body, url)

        payload = r.json()
        total = None
        if isinstance(payload, list):
            total = self._total_from_content_range(r.headers.get("Content-Range"))
            n = len(payload)
            if not page:
                if total is not None and total > n:
                    raise SiloTruncated(n, total, url, rows=payload)
                if total is None and n >= SERVER_ROW_CAP:
                    # No count came back and we are sitting exactly on the cap.
                    # Cannot prove completeness, so do not imply it.
                    raise SiloTruncated(n, None, url, rows=payload)
        return payload, total

    def _get(self, resource: str, params: Dict[str, Any],
             page: bool = False) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        url = f"{self._rest}/{resource}"
        r = self._http.get(url, params={k: v for k, v in params.items() if v is not None})
        return self._check(r, url, page=page)

    def _rpc(self, fn: str, body: Dict[str, Any], page: bool = False) -> Any:
        url = f"{self._rest}/rpc/{fn}"
        r = self._http.post(url, json={k: v for k, v in body.items() if v is not None})
        rows, _ = self._check(r, url, page=page)
        return rows

    # -- discovery ----------------------------------------------------------

    def catalog(self, refresh: bool = False) -> Dict[str, Any]:
        """The metric map + constraints + limits. Cached; the server tells you the rules.

        Warns (`SiloCatalogDrift`) when the server's catalog version is not
        the one this client was written against. Not an error: an agent that
        reads `limits` and `metrics` off the payload keeps working either
        way — the warning is for the wrappers, which are only as current as
        the catalog they were written from.
        """
        if self._catalog is None or refresh:
            self._catalog = self._rpc("catalog", {})
            served = self._catalog.get("version")
            if served != KNOWN_CATALOG_VERSION:
                relation = "newer" if isinstance(served, int) and served > KNOWN_CATALOG_VERSION else "older"
                advice = (
                    "the server may publish endpoints, metrics or limits this "
                    "client does not wrap — read catalog() directly, or upgrade "
                    "silo-client"
                    if relation == "newer" else
                    "some wrappers here may call functions that server does "
                    "not have yet"
                )
                warnings.warn(
                    f"the server's catalog is version {served!r}, {relation} than the "
                    f"{KNOWN_CATALOG_VERSION} this client was written against: {advice}.",
                    SiloCatalogDrift, stacklevel=2,
                )
        return self._catalog

    def metrics(self) -> List[str]:
        return sorted(self.catalog()["metrics"].keys())

    def limits(self) -> Dict[str, Any]:
        """Every ceiling as numbers, from the catalog's `limits` block:
        rows_per_response (the server-wide 1000 and how to detect it),
        sql_sentinel (the functions' own unreachable LIMITs) and the per-tier
        table (panel ids, search_funds/option_chain/option_exercises/
        fund_holdings rows, statement timeout). Empty on a server older than
        catalog v19, which had the same numbers only as prose."""
        return self.catalog().get("limits") or {}

    def coverage(self) -> List[Dict[str, Any]]:
        """Per-dataset freshness and honesty.

        `as_of` is the newest period that has landed AND has actually elapsed;
        `complete_through` is the newest period classified COMPLETE, which is
        what default windows serve; `newest_period` is the newest period KEY
        present, which can sit in the FUTURE when a family files forward-dated
        (FIP is keyed 31-December) — never read it as freshness; `landed_at` is
        when ingest last SUCCEEDED for that source, so a later failed run never
        advances it. `notes` carries a caveat the dates cannot (the
        `funds_fidc` row: delinquency starts 2025-01), null on rows with none.
        """
        return self._rpc("coverage", {})

    def metric_coverage(self) -> List[Dict[str, Any]]:
        """Which (family, metric) pairs are ACTUALLY filed, and over what span.

        `first_period` / `last_period` are the oldest and newest periods
        carrying a non-null value; `filed_rows` / `total_rows` say how dense it
        is. A pair ABSENT from this list is one the family never files — not
        one whose data is late. Use it instead of inferring from nulls in a
        series, which is how a format change gets read as a credit event.
        """
        return self._rpc("metric_coverage", {})

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

    def iter_quote_history(
        self, ticker: str, start: Datish = None, end: Datish = None,
        board: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every quote row, paged with the server's cursor (`p_after`).

        Page 1 is `p_after=''`; each next page is the last row's `trade_date`.
        A page shorter than the 1000-row cap is the last one — nothing is ever
        cut. Rows arrive oldest first.
        """
        body = {"p_ticker": ticker, "p_from": _iso(start), "p_to": _iso(end),
                "p_board": board}
        after = ""
        while True:
            rows = self._rpc("quote_history", {**body, "p_after": after}, page=True)
            for row in rows:
                yield row
            if len(rows) < SERVER_ROW_CAP:
                return
            after = str(rows[-1]["trade_date"])

    def quote_history_all(
        self, ticker: str, start: Datish = None, end: Datish = None,
        board: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """iter_quote_history collected into a list."""
        return list(self.iter_quote_history(ticker, start, end, board))

    def iter_fund_nav(
        self, cnpj: str, entity_type: str, start: Datish = None,
        end: Datish = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every nav row for ONE family, paged with the server's cursor.

        `entity_type` is REQUIRED, and the server enforces it: the cursor is a
        bare period, which is unique only within one family, and 385 CNPJs file
        under two (fi + fidc) in the same month. Paging without it raises
        22023 rather than skipping or repeating a row at a page edge. Use
        `fund_nav()` (no cursor) to see every family at once.
        """
        if not entity_type:
            raise ValueError(
                "iter_fund_nav needs an entity_type (fi, fidc, fii, fip or "
                "fiagro): the cursor is a bare period and one CNPJ can file "
                "under two families in the same month. Use fund_nav() for the "
                "whole result across families."
            )
        body = {"p_cnpj": cnpj, "p_from": _iso(start), "p_to": _iso(end),
                "p_entity_type": entity_type}
        after = ""
        while True:
            rows = self._rpc("fund_nav", {**body, "p_after": after}, page=True)
            for row in rows:
                yield row
            if len(rows) < SERVER_ROW_CAP:
                return
            after = str(rows[-1]["period"])

    def fund_nav_all(
        self, cnpj: str, entity_type: str, start: Datish = None,
        end: Datish = None,
    ) -> List[Dict[str, Any]]:
        """iter_fund_nav collected into a list."""
        return list(self.iter_fund_nav(cnpj, entity_type, start, end))

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

    def fund_debentures(self, cnpj: Optional[str] = None,
                        issuer: Optional[str] = None,
                        start: Datish = None, end: Datish = None,
                        limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """A fund's debenture holdings, or which funds hold an issuer's paper.

        CDA block 6 — its own shape, not a third `kind` of :meth:`fund_holdings`,
        because a debenture's identity is (issuer, maturity, rate structure)
        and those columns have nowhere to go in the equity shape. Exactly one
        of `cnpj` or `issuer`:

            silo.fund_debentures(cnpj="05754060000113")   # what it holds
            silo.fund_debentures(issuer="PETR4")           # who holds Petrobras paper (FCA map)
            silo.fund_debentures(issuer="33000167000101")  # same issuer by CNPJ
            silo.fund_debentures(issuer="02998301000181")  # an UNLISTED issuer — CNPJ is the only way

        Rows are as filed and never summed. `issuer_tickers` is the issuer's
        active listed codes from CVM's published map, None when not listed.
        Rows are clamped to 500 anonymous / 5000 signed in.
        """
        if (cnpj is None) == (issuer is None):
            raise ValueError(
                "fund_debentures needs exactly one of cnpj (what this fund holds) "
                "or issuer (which funds hold this issuer's debentures)"
            )
        return self._rpc("fund_debentures", {
            "p_cnpj": cnpj, "p_issuer": issuer,
            "p_from": _iso(start), "p_to": _iso(end), "p_limit": limit,
        })

    # -- FIDC concentration (informe tabs I, VIII, II, X) ---------------------

    def fidc_cedentes(self, cnpj: Optional[str] = None,
                      cedente: Optional[str] = None,
                      start: Datish = None, end: Datish = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """A FIDC's named originators, or which FIDCs buy from one originator.

        Informe tab I publishes, per fund and month, the nine largest cedentes
        of each block (A = receivables acquired with substantial retention of
        risks and benefits by the originator, B = without) by their own
        CPF/CNPJ and their share OF THAT BLOCK. Exactly one of `cnpj` or
        `cedente`:

            silo.fidc_cedentes(cnpj="05754060000113")      # who this fund buys from
            silo.fidc_cedentes(cedente="61064911000177")   # which funds buy from this CNPJ
            silo.fidc_cedentes(cedente="PETR4")            # a listed originator, via the FCA map

        `share_pct` is a percent of the block, never of the fund. `cedente_id`
        was checksum-verified at ingest; `cedente_tickers` is its active listed
        codes, None when not listed. Slots exist from 2019-11. Rows are clamped
        to 500 anonymous / 5000 signed in.
        """
        if (cnpj is None) == (cedente is None):
            raise ValueError(
                "fidc_cedentes needs exactly one of cnpj (who this fund buys from) "
                "or cedente (which funds buy from this originator)"
            )
        return self._rpc("fidc_cedentes", {
            "p_cnpj": cnpj, "p_cedente": cedente,
            "p_from": _iso(start), "p_to": _iso(end), "p_limit": limit,
        })

    def fidc_sacados(self, cnpj: str, start: Datish = None, end: Datish = None,
                     limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """The 25 largest debtors of one FIDC, as CVM publishes them: anonymized.

        Informe tab VIII carries (rank, value) and nothing else — no debtor
        identity exists in the source, so there is no debtor-side lookup.
        `seq` is CVM's rank as filed and is never recomputed; a fund that files
        fewer than 25 ranks has fewer rows. A concentration ratio is
        `valor / receivables` (the panel metric) in the notebook.
        """
        return self._rpc("fidc_sacados", {
            "p_cnpj": cnpj, "p_from": _iso(start), "p_to": _iso(end), "p_limit": limit,
        })

    def fidc_portfolio(self, cnpj: str, kind: Optional[str] = None,
                       start: Datish = None, end: Datish = None,
                       limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """One FIDC's receivables book, long: (kind, code, parent, item, value).

        `kind`: 'sector' (tab II — TOTAL, the lettered sectors A..K and their
        numbered members; `parent` names the letter a numbered code belongs
        to, so sum leaves or parents, never both), 'scr_debtor' /
        'scr_operation' (tab X — BACEN SCR grades AA..H for the same
        receivables graded two ways), 'tax_debt', or None for all. tab X
        exists from 2023-10 only; earlier months have no scr rows.
        """
        return self._rpc("fidc_portfolio", {
            "p_cnpj": cnpj, "p_kind": kind,
            "p_from": _iso(start), "p_to": _iso(end), "p_limit": limit,
        })

    # -- listed companies (CIA Aberta) ---------------------------------------

    def financials(self, id: str, statement: Optional[str] = None,
                   start: Datish = None, end: Datish = None,
                   scope: str = "con",
                   doc_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Filed financial-statement lines for one listed company.

        `id` is a B3 ticker, a CNPJ, or a CVM code — they resolve to the same
        company through CVM's published FCA map, so the id you price with is
        the id you read fundamentals with:

            silo.financials("PETR4")                      # every statement
            silo.financials("PETR4", statement="DRE")     # income statement
            silo.financials("PETR4", doc_type="dfp")      # annual filings only
            silo.financials("PETR4", scope="ind")         # individual, not consolidated

        One row per account line, exactly as filed. **Read `period_months`
        before comparing rows**: a quarterly filing publishes the same account
        twice under one `ref_date`, once for the three months and once
        year-to-date, and only that span tells them apart — adding them
        double-counts the quarter. `version` carries the restatement: only the
        newest version of each statement is returned.
        """
        return self._rpc("financials", {
            "p_id": id, "p_statement": statement,
            "p_from": _iso(start), "p_to": _iso(end),
            "p_scope": scope, "p_doc_type": doc_type,
        })

    def company_financials(self, id: str, start: Datish = None,
                           end: Datish = None,
                           scope: str = "con") -> List[Dict[str, Any]]:
        """Headline financials for one company, one row per filed period.

        The convenience shape over :meth:`financials`: revenue, gross profit,
        net income, total assets, equity, net margin and ROE per
        (document, reference date, period span).

            silo.company_financials("PETR4")

        `roe_pct` is the period's return on equity and is **not** annualised —
        a three-month row divides one quarter's profit by equity; `period_months`
        says which span you are looking at. A balance sheet filed under a
        different version than the income statement reads NULL rather than
        being paired across filings.
        """
        return self._rpc("company_financials", {
            "p_id": id, "p_from": _iso(start), "p_to": _iso(end),
            "p_scope": scope,
        })

    # -- industry aggregates (ANBIMA) ----------------------------------------

    def anbima_classes(self, category: Optional[str] = None,
                       metric: Optional[str] = None,
                       level: Optional[str] = "category",
                       start: Datish = None,
                       end: Datish = None) -> List[Dict[str, Any]]:
        """ANBIMA Boletim de Fundos class series, as published.

            silo.anbima_classes()                                  # every class, AUM/flows/returns/counts
            silo.anbima_classes("Renda Fixa", metric="pl_brl_mm")  # one class, one metric
            silo.anbima_classes("Ações", level="type")             # the ANBIMA types under a class
            silo.anbima_classes(level="total")                     # the industry total

        One row per (reference_date, category, type, level, metric); `unit`
        is brl_mm (R$ millions, as published), pct (percentage points) or
        count. These are industry aggregates: no fund is mapped to a class
        here, so nothing joins them to `fund_nav` or `panel`. An unknown
        category, metric or level is a `SiloError` (22023) listing what
        exists — never an empty list that looks like "nothing published".
        """
        return self._rpc("anbima_classes", {
            "p_category": category, "p_metric": metric, "p_level": level,
            "p_from": _iso(start), "p_to": _iso(end),
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
        """Read one of the typed views — one page.

            client.view("equities", cd_ativo="eq.PETR4", limit=10)
            client.view("funds", entity_type="eq.fidc", order="cnpj.asc",
                        limit=1000, offset=1000)          # page two

        Filter syntax is PostgREST's own, passed through verbatim — the SDK
        does not invent a query language over it.

        Views are the one surface that pages, so the truncation rule bends
        here and nowhere else: with an explicit `limit` or `offset` you asked
        for a page and get that page, whatever the total. Without either, a
        response that hits the server's 1000-row cap raises `SiloTruncated`
        exactly as a function call would — the registry is large, and a
        1000-row `funds` view with no `limit` is a silent cut, not a result.
        Use :meth:`view_all` to walk every page.
        """
        if name not in self.VIEWS:
            raise ValueError(f"unknown view {name!r}; served views are {list(self.VIEWS)}")
        paged = "limit" in filters or "offset" in filters
        rows, _ = self._get(name, filters, page=paged)
        return rows

    def view_all(self, name: str, page_size: int = SERVER_ROW_CAP,
                 **filters: Any) -> List[Dict[str, Any]]:
        """Every row of a view, paged with limit/offset until the server runs out.

            fidcs = client.view_all("funds", entity_type="eq.fidc",
                                    order="cnpj.asc",
                                    select="cnpj,fund_name,first_period,last_period")

        `order` is REQUIRED: offset paging without a total order is not
        stable, and an unstable page boundary duplicates one row and drops
        another with nothing to say so — which is fabrication by omission.
        `page_size` is clamped to the server's 1000-row cap (a larger limit is
        silently reduced server-side anyway). Stops when a page comes back
        short, or when Content-Range says the total has been reached.
        """
        return list(self.iter_view(name, page_size=page_size, **filters))

    def iter_view(self, name: str, page_size: int = SERVER_ROW_CAP,
                  **filters: Any) -> Iterator[Dict[str, Any]]:
        """:meth:`view_all` as a generator — same contract, row by row."""
        if name not in self.VIEWS:
            raise ValueError(f"unknown view {name!r}; served views are {list(self.VIEWS)}")
        if "limit" in filters or "offset" in filters:
            raise ValueError(
                "view_all/iter_view page for you; pass page_size instead of "
                "limit, and no offset. Use view() for one explicit page."
            )
        if not filters.get("order"):
            raise ValueError(
                "view_all/iter_view need an `order` (e.g. order='cnpj.asc'): "
                "offset paging without a total order can duplicate or drop rows "
                "at page boundaries without saying so"
            )
        size = max(1, min(int(page_size), SERVER_ROW_CAP))
        offset = 0
        while True:
            rows, total = self._get(
                name, {**filters, "limit": size, "offset": offset}, page=True,
            )
            for row in rows:
                yield row
            offset += len(rows)
            if len(rows) < size:
                return
            if total is not None and offset >= total:
                return

    # -- the primitive ------------------------------------------------------

    def _panel_body(self, ids, metrics, start, end, freq, entity_type,
                    min_nav, min_months) -> Dict[str, Any]:
        known = set(self.catalog()["metrics"].keys())
        bad = [m for m in metrics if m not in known]
        if bad:
            raise ValueError(
                f"unknown metric(s) {bad}; the catalog serves {sorted(known)}"
            )
        if not ids and not entity_type:
            raise ValueError(
                "pass ids, or entity_type= to walk a whole family (universe "
                "mode, signed-in callers only)"
            )
        return {
            "p_ids": list(ids) if ids else [], "p_metrics": list(metrics),
            "p_from": _iso(start), "p_to": _iso(end), "p_freq": freq,
            "p_entity_type": entity_type, "p_min_nav": min_nav,
            "p_min_months": min_months,
        }

    @staticmethod
    def _pivot(rows: List[Dict[str, Any]], entity_type: Optional[str]):
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
        # The server's grain is (id, asset_class, date, metric): a CNPJ that
        # files under two families (fi + fidc) comes back twice per month.
        # Averaging or "first"-picking those silently would hand back a
        # vehicle that does not exist — refuse and say how to disambiguate.
        dup = df.duplicated(["date", "id", "metric"], keep=False)
        if dup.any():
            offenders = sorted(df.loc[dup, "id"].unique().tolist())
            raise ValueError(
                f"panel is not unique on (id, date, metric): {offenders} file "
                "under more than one asset_class in the window. Pass "
                "entity_type='fi'|'fidc'|... to keep one family, or use "
                "wide=False and keep asset_class in your own pivot key."
            )
        return df.pivot_table(
            index="date", columns=["id", "metric"], values="value",
            aggfunc="first",  # the grain is unique (checked above); never averages
        ).sort_index()

    def panel(
        self,
        ids: Optional[Sequence[str]],
        metrics: Sequence[str] = ("close", "nav"),
        start: Datish = None,
        end: Datish = None,
        freq: str = "month",
        wide: bool = True,
        entity_type: Optional[str] = None,
        min_nav: Optional[float] = None,
        min_months: Optional[int] = None,
    ):
        """The (id, date, metric, value) panel — the API's one primitive.

        Whole-result mode: the server REFUSES (`SiloOverCap`) a window that
        would exceed one 1000-row page rather than trim it. Use
        `iter_panel` / `panel_all` to page, or narrow the request.

        Metric names are validated against the live catalog so a typo fails
        HERE, loudly, instead of returning an empty panel that looks like
        missing data. `end=None` keeps the server's honest window for fund
        metrics. `entity_type` keeps one fund family (a CNPJ can file under
        two). `ids=None` with `entity_type` is universe mode: the family's
        funds, optionally filtered by `min_nav` (latest NAV, BRL) and
        `min_months` (non-null observations of the first metric); signed-in
        callers only. wide=True pivots to a DataFrame with (date) index and
        (id, metric) columns; missing observations stay NaN — never filled —
        and a duplicate (id, date, metric) raises instead of being averaged.
        """
        rows = self._rpc("panel", self._panel_body(
            ids, metrics, start, end, freq, entity_type, min_nav, min_months,
        ))
        if not wide:
            return rows
        return self._pivot(rows, entity_type)

    def iter_panel(
        self,
        ids: Optional[Sequence[str]] = None,
        metrics: Sequence[str] = ("close", "nav"),
        start: Datish = None,
        end: Datish = None,
        freq: str = "month",
        entity_type: Optional[str] = None,
        min_nav: Optional[float] = None,
        min_months: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Every panel row, paged with the server's cursor (`p_after`).

        Page 1 is `p_after=''`; each next page is the last row's
        `date|id|metric|asset_class`. A page shorter than the 1000-row cap is
        the last one — nothing is ever cut. Rows arrive ordered by
        (date, id, metric, asset_class).
        """
        body = self._panel_body(ids, metrics, start, end, freq, entity_type,
                                min_nav, min_months)
        after = ""
        while True:
            rows = self._rpc("panel", {**body, "p_after": after}, page=True)
            for row in rows:
                yield row
            if len(rows) < SERVER_ROW_CAP:
                return
            last = rows[-1]
            after = f"{last['date']}|{last['id']}|{last['metric']}|{last.get('asset_class') or ''}"

    def panel_all(
        self,
        ids: Optional[Sequence[str]] = None,
        metrics: Sequence[str] = ("close", "nav"),
        start: Datish = None,
        end: Datish = None,
        freq: str = "month",
        wide: bool = False,
        entity_type: Optional[str] = None,
        min_nav: Optional[float] = None,
        min_months: Optional[int] = None,
    ):
        """`list(iter_panel(...))`, optionally pivoted wide (same duplicate
        guard as `panel`). The way to pull a whole family: `panel_all(None,
        ["delinquency", "nav"], entity_type="fidc", min_months=12)`."""
        rows = list(self.iter_panel(ids, metrics, start, end, freq,
                                    entity_type, min_nav, min_months))
        if not wide:
            return rows
        return self._pivot(rows, entity_type)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SiloClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
