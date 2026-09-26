"""Parse and upsert B3's full cash-distribution history into b3_cash_dividend.

Why this table exists, why it carries no ISIN, and how the ISIN is resolved
against the tape: src/store/migrations/48_b3_cash_dividend.sql. This module
only maps B3's field names and formats (dd/mm/yyyy dates, decimal-comma
numbers — the same parsers as the corporate-events ingest) and upserts.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from src.pipeline.ingest_b3_events import _parse_date, _parse_decimal

logger = logging.getLogger(__name__)

TABLE = "b3_cash_dividend"
# upsert_rows takes a COMMA-SEPARATED STRING (see ingest_b3_events).
CONFLICT_COLS = (
    "trading_name,type_stock,corporate_action,"
    "last_date_prior_ex,date_approval,value_cash,occurrence"
)


def parse_cash_dividends(
    issuing_company: str,
    trading_name: str,
    rows: List[Dict[str, Any]],
    since: Optional[date] = None,
    cnpj: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Turn GetListedCashDividends results into upsertable records.

    A row with no share class or no corporate action cannot be keyed or joined
    to the tape, so it is dropped and counted, never filled in. `since` keeps
    only distributions whose entitlement date is on or after it (the daily
    run fetches every page, see the fetcher, but only re-upserts the recent
    tail). A row whose date does not parse is kept by a full-history run and
    dropped by a windowed one: it cannot be shown to fall inside the window.
    `cnpj` is B3's catalog CNPJ for the company; it is what lets the ISIN view
    reach tickers the company traded under before a rename (cia_ticker).
    """
    records: List[Dict[str, Any]] = []
    dropped = 0
    # Byte-identical rows are separate installments (see migration 48,
    # `occurrence`); number them so the key keeps every one.
    seen: Dict[str, int] = {}
    for row in rows:
        type_stock = (row.get("typeStock") or "").strip().upper()
        action = (row.get("corporateAction") or "").strip().upper()
        if not type_stock or not action:
            dropped += 1
            continue
        fingerprint = json.dumps(row, sort_keys=True, default=str)
        seen[fingerprint] = seen.get(fingerprint, 0) + 1
        occurrence = seen[fingerprint]
        last_prior = _parse_date(row.get("lastDatePriorEx"))
        if since is not None and (last_prior is None or last_prior < since):
            continue
        records.append(
            {
                "issuing_company": issuing_company.strip().upper(),
                "trading_name": trading_name.strip(),
                "cnpj": cnpj,
                "type_stock": type_stock,
                "corporate_action": action,
                "date_approval": _parse_date(row.get("dateApproval")),
                "last_date_prior_ex": last_prior,
                "value_cash": _parse_decimal(row.get("valueCash")),
                "ratio": _parse_decimal(row.get("ratio")),
                "quoted_per_shares": _parse_decimal(row.get("quotedPerShares")),
                "date_closing_price_prior_ex": _parse_date(
                    row.get("dateClosingPricePriorExDate")
                ),
                "closing_price_prior_ex": _parse_decimal(
                    row.get("closingPricePriorExDate")
                ),
                "corporate_action_price": _parse_decimal(
                    row.get("corporateActionPrice")
                ),
                "occurrence": occurrence,
                "raw": row,
                "source": "b3_listed_cash_dividends",
            }
        )
    if dropped:
        logger.warning(
            "%s: dropped %d cash-dividend rows with no typeStock or corporateAction",
            trading_name, dropped,
        )
    return records


def ingest_b3_cash_dividends(conn: Any, records: List[Dict[str, Any]]) -> int:
    """Upsert parsed records. Returns the number of rows written."""
    if not records:
        return 0
    from src.store.pg_client import upsert_rows

    return upsert_rows(conn, TABLE, records, CONFLICT_COLS)
