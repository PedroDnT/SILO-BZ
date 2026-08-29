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


class SiloError(RuntimeError):
    """An API-level failure. Carries the HTTP status and the server's body —
    the server's error text (e.g. option_chain's required-prefix message) is
    the useful part, so it is never swallowed."""

    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")


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
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        base = (url or os.environ.get("SILO_URL", "")).rstrip("/")
        if not base:
            raise ValueError("url is required (or set SILO_URL)")
        self._key = key or os.environ.get("SILO_ANON_KEY", "")
        if not self._key:
            raise ValueError("key is required (or set SILO_ANON_KEY)")
        self._rest = f"{base}/rest/v1"
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"apikey": self._key, "Accept": "application/json"},
        )
        self._catalog: Optional[Dict[str, Any]] = None

    # -- plumbing -----------------------------------------------------------

    def _get(self, resource: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self._rest}/{resource}"
        r = self._http.get(url, params={k: v for k, v in params.items() if v is not None})
        if r.status_code >= 400:
            raise SiloError(r.status_code, r.text, url)
        return r.json()

    def _rpc(self, fn: str, body: Dict[str, Any]) -> Any:
        url = f"{self._rest}/rpc/{fn}"
        r = self._http.post(url, json={k: v for k, v in body.items() if v is not None})
        if r.status_code >= 400:
            raise SiloError(r.status_code, r.text, url)
        return r.json()

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
            "p_codneg": ticker, "p_from": _iso(start), "p_to": _iso(end),
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
                     expiry_from: Datish = None, limit: int = 500) -> List[Dict[str, Any]]:
        return self._rpc("option_chain", {
            "p_prefix": prefix, "p_trade_date": _iso(trade_date),
            "p_expiry_from": _iso(expiry_from), "p_limit": limit,
        })

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
        import pandas as pd  # deferred: long-format callers never pay for it

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
