"""B3 listed-companies corporate events (splits, groupings, bonuses, dividends).

WHY THIS EXISTS
---------------
`b3_cotahist` stores the tape exactly as B3 published it: unadjusted. A 2:1
split therefore shows up as a ~50% overnight "return" with no market move
behind it, and every price series that crosses one is wrong for any use that
compares levels across the event.

The ONLY honest way to fix that is an event table sourced from published
corporate actions — never inferred from the price series itself. A jump-shaped
gap in a price is evidence of nothing in particular: it can be a split, a
delisting-and-relisting, a fat-finger print, or a real crash. Guessing a factor
from the jump would fabricate the very number the adjustment depends on, which
this repository forbids (CLAUDE.md rule 1).

THE SOURCE
----------
B3's public listed-companies proxy, the same JSON the
sistemaswebb3-listados.b3.com.br company pages call:

    GET {BASE}/GetListedSupplementCompany/{base64 json}
    GET {BASE}/GetInitialCompanies/{base64 json}

Three quirks, all load-bearing:

1. Parameters are a base64-encoded JSON object in the PATH, not a query string.
   A bare GET with no token returns 200 and an empty body, which is what made
   an earlier probe conclude the endpoint was dead.
2. GetListedSupplementCompany double-encodes its response: the body is a JSON
   *string* that itself contains the JSON array. `_decode` unwraps until it
   stops being a string.
3. GetListedSupplementCompany also returns 200 / empty for an issuing code
   that is not in the listed-companies catalog. That is not a malformed
   token: PETR returns a body with the same encoding, ADMF (the ticker
   prefix of ADMF3 / B100 S.A., whose catalog key is B100) returns none.
   `B3SupplementEmpty` is that case. A token that is actually malformed
   empties *every* issuer; the ingestor treats that as a slice error.

WHAT IT CARRIES (verified live 2026-08-28)
------------------------------------------
`stockDividends` — the ones that change the share count, i.e. the ones price
adjustment actually needs:

    label            factor        meaning
    DESDOBRAMENTO    100.0         split: 100 new shares per 100 held
    GRUPAMENTO       0.1           reverse split
    BONIFICACAO      5.0           bonus shares

`cashDividends` — DIVIDENDO / JRS CAP PROPRIO with a per-share `rate`; stored
for a future total-return series, not used by price adjustment.

`subscriptions` — rights offerings with percentage and price.

Every record carries `isinCode` (the join key to b3_cotahist.isin) and
`lastDatePrior` — the LAST session on which the old entitlement still applied.
The ex-date is the following session; deriving one from the other is a trading
calendar question, so both this fetcher and the table keep B3's own field and
leave that derivation to the consumer.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall"
)

# B3 rejects requests without a browser-ish UA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://sistemaswebb3-listados.b3.com.br/listedCompaniesPage/",
}

# Event labels that change the share count, and therefore the price series.
# Anything else in stockDividends is stored but not used for adjustment.
PRICE_AFFECTING_LABELS = {"DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO"}


def cash_dividend_query_name(trading_name: str) -> str:
    """tradingName as B3's own page sends it to GetListedCashDividends.

    B3's frontend does ``toUpperCase().trim()`` and then removes the FIRST
    space, dash, underscore and slash (JavaScript's string ``replace``). The
    server ignores spaces, dots and dashes, but a name that keeps its slash
    matches nothing: ``KLABIN S/A`` returns 0 records, ``KLABIN SA`` 219
    (docs/research/cash-dividends-mapping.md §1). No issuer on the tape since
    2019 has two slashes, so first-only is enough, and it is what B3 does.
    """
    name = trading_name.upper().strip()
    for ch in (" ", "-", "_", "/"):
        name = name.replace(ch, "", 1)
    return name


class B3SupplementEmpty(LookupError):
    """GetListedSupplementCompany returned HTTP 200 with an empty body.

    B3 does this for issuing codes that are not in the listed-companies
    catalog. ``left(codneg, 4)`` from the tape is usually the catalog key
    (PETR4 → PETR) but not always (ADMF3 trades as B100 S.A.). Distinct from
    a malformed path token, which empties every issuer in the sweep.
    """


class B3CorporateEventsFetcher:
    """Fetch published corporate events from B3's listed-companies proxy."""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        sleep_between: float = 0.2,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep_between = sleep_between
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    # -- transport ----------------------------------------------------------
    @staticmethod
    def _token(payload: Dict[str, Any]) -> str:
        return base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

    @staticmethod
    def _decode(body: str) -> Any:
        """Unwrap B3's double-encoded payloads.

        GetListedSupplementCompany returns a JSON string containing the JSON
        array; GetInitialCompanies returns the object directly. Loop until the
        value stops being a string so both shapes work.
        """
        value: Any = json.loads(body)
        seen = 0
        while isinstance(value, str) and seen < 3:
            value = json.loads(value)
            seen += 1
        return value

    def _call(self, endpoint: str, payload: Dict[str, Any]) -> Any:
        """GET one endpoint. Raises on exhausted retries — never returns a stub.

        A failed fetch must raise so the caller logs an error row; returning an
        empty list here would silently publish "this company has no splits",
        which is a fabricated fact.
        """
        url = f"{BASE_URL}/{endpoint}/{self._token(payload)}"
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                text = response.text.strip()
                if not text:
                    if endpoint == "GetListedSupplementCompany":
                        # HTTP 200 / empty is B3's "this issuing code is not
                        # in the listed-companies catalog" (verified 2026-08-30:
                        # ADMF vs PETR vs B100). Retrying does not fill it.
                        # A malformed path token also empties the body — but
                        # then every issuer is empty, which the ingestor
                        # treats as a slice error.
                        raise B3SupplementEmpty(
                            f"{endpoint} returned an empty body for {payload!r}"
                        )
                    raise ValueError(
                        f"{endpoint} returned an empty body for {payload!r} — "
                        "B3 answers 200 with no content when the path token is "
                        "malformed"
                    )
                return self._decode(text)
            except B3SupplementEmpty:
                raise
            except Exception as exc:  # noqa: BLE001 - re-raised below
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.sleep_between * (2 ** attempt))
        raise RuntimeError(
            f"B3 {endpoint} failed after {self.max_retries} attempts "
            f"for {payload!r}: {last_error}"
        ) from last_error

    # -- public surface -----------------------------------------------------
    def list_companies(self, page_size: int = 120) -> Iterator[Dict[str, Any]]:
        """Yield every listed company B3 knows (code, name, CNPJ, status).

        Paged; the first response reports totalPages. ~3,500 companies as of
        2026-08.
        """
        page = 1
        while True:
            data = self._call(
                "GetInitialCompanies",
                {"language": "pt-br", "pageNumber": page, "pageSize": page_size},
            )
            results = (data or {}).get("results") or []
            for row in results:
                yield row
            total_pages = int(((data or {}).get("page") or {}).get("totalPages") or 0)
            if page >= total_pages or not results:
                return
            page += 1
            time.sleep(self.sleep_between)

    def trading_names(self, page_size: int = 120) -> Dict[str, List[Dict[str, str]]]:
        """issuingCompany -> [{trading_name, cnpj}] as B3's catalog lists them.

        GetListedCashDividends is keyed by tradingName, matched exactly (ITAU
        returns nothing; ITAUSA and ITAUUNIBANCO are different companies), so
        the name must come from B3's own catalog, never be derived from a
        ticker. The catalog lists ACTIVE companies under their CURRENT code
        (Eletrobras is AXIA, not ELET); the CNPJ is kept because it is what
        links a renamed company back to its old tickers (cia_ticker). A code
        listed under more than one name keeps all of them.
        """
        names: Dict[str, List[Dict[str, str]]] = {}
        for row in self.list_companies(page_size=page_size):
            code = (row.get("issuingCompany") or "").strip().upper()
            name = (row.get("tradingName") or "").strip()
            if not code or not name:
                continue
            entries = names.setdefault(code, [])
            if all(e["trading_name"] != name for e in entries):
                # B3 serves the CNPJ as a number in places, dropping leading
                # zeros (Banco do Brasil 00000000000191 arrives as "191").
                # Restoring them is formatting, not inference: a CNPJ is 14
                # digits by definition. Anything longer is left empty.
                digits = "".join(ch for ch in str(row.get("cnpj") or "") if ch.isdigit())
                cnpj = digits.zfill(14) if 0 < len(digits) <= 14 else ""
                entries.append({"trading_name": name, "cnpj": cnpj})
        return names

    def fetch_cash_dividends(
        self, trading_name: str, page_size: int = 120
    ) -> List[Dict[str, Any]]:
        """Every published cash distribution for one tradingName, all pages.

        B3 sorts this endpoint by typeStock and THEN by date, so page one of a
        multi-class issuer is typically all ON (PETR: page one ON back to
        2007, PN only from page two). Stopping early would drop whole share
        classes, so this always pages to totalPages; callers narrow by date
        after the fetch, not by fetching less.

        Unlike the supplement's ~12-month cashDividends array, this history
        is complete (PETR: 343 rows back to 1996, verified 2026-09-26).

        The name is sent normalized as B3's own page sends it
        (cash_dividend_query_name): a name that still carries its slash
        ("KLABIN S/A") gets totalRecords 0, which the count check below would
        accept as "no dividends".
        """
        query_name = cash_dividend_query_name(trading_name)
        rows: List[Dict[str, Any]] = []
        page = 1
        while True:
            data = self._call(
                "GetListedCashDividends",
                {
                    "language": "pt-br",
                    "pageNumber": page,
                    "pageSize": page_size,
                    "tradingName": query_name,
                },
            )
            if not isinstance(data, dict):
                raise ValueError(
                    f"unexpected cash-dividend payload for {trading_name!r}: "
                    f"{type(data).__name__}"
                )
            results = data.get("results") or []
            rows.extend(r for r in results if isinstance(r, dict))
            page_info = data.get("page") or {}
            if page_info.get("totalRecords") is None:
                # A page size over B3's silent cap (200 does it; 120 works)
                # returns HTTP 200, no results and a null total. A company
                # with no distributions reports 0, not null.
                raise ValueError(
                    f"GetListedCashDividends for {trading_name!r} returned no "
                    f"totalRecords (pageSize {page_size} over B3's cap?)"
                )
            total_pages = int(page_info.get("totalPages") or 0)
            if page >= total_pages or not results:
                # A short read would publish "no dividends before X" for a
                # company that has them; count against B3's own total.
                total_records = int(page_info.get("totalRecords") or 0)
                if len(rows) != total_records:
                    raise ValueError(
                        f"GetListedCashDividends for {trading_name!r} returned "
                        f"{len(rows)} rows but reports totalRecords={total_records}"
                    )
                return rows
            page += 1
            time.sleep(self.sleep_between)

    def fetch_company_events(self, issuing_company: str) -> Dict[str, Any]:
        """All published events for one issuing company code (e.g. 'PETR').

        Returns the supplement record with its three event arrays. A company
        with no events returns the record with empty arrays — which is B3
        saying "none", not us guessing.
        """
        data = self._call(
            "GetListedSupplementCompany",
            {"issuingCompany": issuing_company, "language": "pt-br"},
        )
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            raise ValueError(
                f"unexpected supplement payload for {issuing_company}: "
                f"{type(data).__name__}"
            )
        return data

    def fetch_events(self, issuing_company: str) -> List[Dict[str, Any]]:
        """Flatten one company's events into rows ready for validation.

        Each row keeps B3's own field names inside `raw`, so nothing published
        is lost even where this mapping ignores it.
        """
        record = self.fetch_company_events(issuing_company)
        rows: List[Dict[str, Any]] = []
        for event_class, key in (
            ("stock", "stockDividends"),
            ("cash", "cashDividends"),
            ("subscription", "subscriptions"),
        ):
            for item in record.get(key) or []:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "issuing_company": issuing_company,
                        "event_class": event_class,
                        "isin": (item.get("isinCode") or item.get("assetIssued") or "").strip()
                        or None,
                        "label": (item.get("label") or "").strip().upper() or None,
                        "last_date_prior": item.get("lastDatePrior"),
                        "approved_on": item.get("approvedOn"),
                        "factor": item.get("factor"),
                        "rate": item.get("rate"),
                        "payment_date": item.get("paymentDate"),
                        "raw": item,
                    }
                )
        return rows
