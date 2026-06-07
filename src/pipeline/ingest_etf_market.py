"""Ingest ETF market snapshots scraped from etfsbrasil.com.br via Apify.

FETCH (src/fetchers/apify_etf_fetcher.ApifyETFFetcher)
  → PARSE (here: Brazilian number/date formats → etf_market_snapshot columns)
  → STORE (pg_client.upsert_rows, idempotent on (ticker, snapshot_date)).

NOT wired into the daily run yet: the scraper's JS-rendered NAV/cotistas selectors
must be verified against one real Apify run first (see docs/ETF_AND_PERFORMANCE.md).
Run manually:  APIFY_TOKEN=… python -m src.pipeline.ingest_etf_market

Data-integrity: a row that fails validation (no ticker) is dropped and counted,
never coerced; a failed scrape raises (in the fetcher). One scrape → rows upserted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.fetchers.apify_etf_fetcher import ApifyETFFetcher
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

TABLE = "etf_market_snapshot"
CONFLICT = "ticker,snapshot_date"


# ---------------------------------------------------------------------------
# Brazilian-format parsers (decimal comma, thousands dot, %, R$, dd/mm/yyyy).
# All return None on empty / placeholder ("-", "N/A", "") rather than guessing.
# ---------------------------------------------------------------------------

_EMPTY = {"", "-", "--", "n/a", "na", "nd", "—"}


def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _EMPTY else s


def _num(v: Any) -> Optional[float]:
    """Parse a Brazilian numeric string (e.g. '1.234,56', '0,10', '-46,93')."""
    s = _clean(v)
    if s is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)           # strip R$, %, spaces, etc.
    if s in {"", "-"}:
        return None
    s = s.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    try:
        return float(s)
    except ValueError:
        return None


def _pct(v: Any) -> Optional[float]:
    """Percent value as a number (4,91% -> 4.91)."""
    return _num(v)


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(round(n)) if n is not None else None


def _date(v: Any) -> Optional[str]:
    s = _clean(v)
    if s is None:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _ticker(v: Any) -> Optional[str]:
    s = _clean(v)
    if s is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    return s or None


def _record_to_row(rec: Dict[str, Any], snapshot: str) -> Optional[Dict[str, Any]]:
    ticker = _ticker(rec.get("ticker"))
    if not ticker:
        return None
    return {
        "ticker":           ticker,
        "snapshot_date":    snapshot,
        "source":           "etfsbrasil",
        "fund_name":        _clean(rec.get("fund_name")),
        "categoria":        _clean(rec.get("categoria")),
        "regiao":           _clean(rec.get("regiao")),
        "indice":           _clean(rec.get("indice")),
        "provedor_indice":  _clean(rec.get("provedor_indice")),
        "taxa_adm_pct":     _pct(rec.get("taxa_adm")),
        "nav":              _num(rec.get("nav")),
        "cotistas":         _int(rec.get("cotistas")),
        "price":            _num(rec.get("price")),
        "ret_ytd_pct":      _pct(rec.get("ret_ytd")),
        "ret_12m_pct":      _pct(rec.get("ret_12m")),
        "ret_36m_pct":      _pct(rec.get("ret_36m")),
        "vol_12m_pct":      _pct(rec.get("vol_12m")),
        "sharpe_12m":       _num(rec.get("sharpe_12m")),
        "max_drawdown_pct": _pct(rec.get("max_drawdown")),
        "launch_date":      _date(rec.get("launch")),
        "raw":              Json(rec),
    }


def _active_tickers(conn) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM cvm_etf_registry "
            "WHERE ticker IS NOT NULL AND COALESCE(is_active, true) ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall()]


def ingest_etf_market(conn, tickers: Optional[List[str]] = None) -> int:
    """Scrape etfsbrasil for `tickers` (default: active registry ETFs) and upsert."""
    tickers = tickers or _active_tickers(conn)
    if not tickers:
        raise RuntimeError(
            "No ETF tickers to scrape — seed cvm_etf_registry first (ingest_etf_registry)"
        )
    records = ApifyETFFetcher().fetch(tickers)
    snapshot = datetime.now().date().isoformat()

    rows, dropped = [], 0
    for rec in records:
        row = _record_to_row(rec, snapshot)
        if row is None:
            dropped += 1
            continue
        rows.append(row)
    if dropped:
        logger.warning("etf_market: dropped %d scraped records without a ticker", dropped)
    if not rows:
        raise RuntimeError("etf_market: scrape returned records but none had a usable ticker")

    written = upsert_rows(conn, TABLE, rows, conflict_columns=CONFLICT)
    logger.info("etf_market: upserted %d ETF snapshots for %s", written, snapshot)
    return written


async def _run() -> int:
    logging.basicConfig(level=logging.INFO)
    conn = get_pg_client()
    return ingest_etf_market(conn)


if __name__ == "__main__":
    print("etf_market snapshots upserted:", asyncio.run(_run()))
