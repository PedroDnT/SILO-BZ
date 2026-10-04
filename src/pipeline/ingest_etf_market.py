"""Ingest ETF market snapshots scraped from etfsbrasil.com.br via Apify.

FETCH (src/fetchers/apify_etf_fetcher.ApifyETFFetcher)
  → PARSE (here: Brazilian number/date formats → etf_market_snapshot columns)
  → STORE (pg_client.upsert_rows, idempotent on (ticker, snapshot_date)).

Wired into run_daily when APIFY_TOKEN is set (self-skips when unset, and when
Apify never returns a dataset: 403 actor-not-approved, 403 usage hard limit,
408/wait timeout, or platform ABORTED).
See docs/reference/ETF_AND_PERFORMANCE.md.
Run manually:  APIFY_TOKEN=… python -m src.pipeline.ingest_etf_market

Data-integrity: a row that fails validation (no ticker) is dropped and counted,
never coerced; a failed scrape raises (in the fetcher). One scrape → rows upserted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.fetchers.apify_etf_fetcher import ApifyETFFetcher, ApifyScrapeUnavailableError
from src.pipeline import ingest_log
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


def _cnpj14(v: Any) -> Optional[str]:
    s = _clean(v)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 14 else None  # CNPJ is 14 digits or it's not one


# The /etfs/<ticker> page is rendered text (innerText). Every figure in the info
# block is label-then-value, one per line ("NÚMERO DE COTISTAS\n105.270"). The
# NAV/cotistas/taxa patterns used to assume value-then-label, so they matched the
# number above a LATER label: the cotistas and PL charts print their date range
# ("24 de set. de 2026") right above "Número de cotistas" / "Patrimônio líquido",
# and a year landed in 178/178 cotistas and 26 NAVs (checked 2026-09-30). Those
# three now go through _labelled_line: the FIRST line that is exactly the label,
# then the next line, kept only if the whole line has the expected shape — never
# a fall-through to a later occurrence. Returns are chart-rendered (not in text)
# so they stay NULL until mapped from the next_data JSON post-verify.
_RE = {
    "price":    r"R\$\s*([\d.,]+)",
    "fund_name": r"Nome do fundo\s*\n+\s*([^\n]+)",
    "indice":   r"\n[ÍI]ndice\s*\n+\s*\[?([^\n\]]+)",
    "provedor": r"Provedor do [íi]ndice\s*\n+\s*\[?([^\n\]]+)",
    "regiao":   r"Regi[ãa]o\s*\n+\s*([^\n]+)",
    "launch":   r"Lan[cç]amento\s*\n+\s*(\d{2}/\d{2}/\d{4})",
    "cnpj":     r"CNPJ\s*\n+\s*([\d./\-]+)",
    "isin":     r"ISIN\s*\n+\s*([A-Z0-9]{12})",
}

# (label line, shape the whole next line must have). Brazilian format: "." groups
# thousands, "," is the decimal mark.
_LABELLED = {
    "nav_mm":   (r"Patrim[oô]nio l[ií]quido \(R\$ MM\)", r"\d{1,3}(?:\.\d{3})*(?:,\d+)?"),
    "cotistas": (r"N[uú]mero de cotistas",                 r"\d{1,3}(?:\.\d{3})*"),
    "taxa_adm": (r"Taxa de administra[cç][aã]o total",     r"\d+(?:,\d+)?\s*%"),
}


def _grab(text: Optional[str], pattern: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _labelled_line(text: Optional[str], key: str) -> Optional[str]:
    """The line after the first line that is exactly the label, if it has the shape.

    Anything else (no label, a chart heading followed by "Zoom", a placeholder)
    is None: a missing value stays a gap, never the nearest number on the page.
    """
    if not text:
        return None
    label, shape = _LABELLED[key]
    m = re.search(rf"^[ \t]*{label}[ \t]*\n+[ \t]*([^\n]*)", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    return value if re.fullmatch(shape, value) else None


def _record_to_row(rec: Dict[str, Any], snapshot: str) -> Optional[Dict[str, Any]]:
    ticker = _ticker(rec.get("ticker"))
    if not ticker:
        return None
    text = rec.get("text")
    nav_mm = _num(_labelled_line(text, "nav_mm"))   # page shows R$ MM
    return {
        "ticker":           ticker,
        "snapshot_date":    snapshot,
        "source":           "etfsbrasil",
        "cnpj":             _cnpj14(_grab(text, _RE["cnpj"])),
        "isin":             _clean(_grab(text, _RE["isin"])),
        "fund_name":        _clean(_grab(text, _RE["fund_name"])),
        "categoria":        None,   # shown next to the ticker, not label-tagged
        "regiao":           _clean(_grab(text, _RE["regiao"])),
        "indice":           _clean(_grab(text, _RE["indice"])),
        "provedor_indice":  _clean(_grab(text, _RE["provedor"])),
        "taxa_adm_pct":     _pct(_labelled_line(text, "taxa_adm")),
        "nav":              (nav_mm * 1_000_000) if nav_mm is not None else None,
        "cotistas":         _int(_labelled_line(text, "cotistas")),
        "price":            _num(_grab(text, _RE["price"])),
        "ret_ytd_pct":      None,
        "ret_12m_pct":      None,
        "ret_36m_pct":      None,
        "vol_12m_pct":      None,
        "sharpe_12m":       None,
        "max_drawdown_pct": None,
        "launch_date":      _date(_grab(text, _RE["launch"])),
        "raw":              Json(rec),
    }


def _active_tickers(conn) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM cvm_etf_registry "
            "WHERE ticker IS NOT NULL AND COALESCE(is_active, true) ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall()]


LOG_ENTITY = "etf_market"
LOG_DOC_TYPE = "snapshot"


async def ingest_etf_market(conn, tickers: Optional[List[str]] = None) -> int:
    """Scrape etfsbrasil for `tickers` (default: active registry ETFs) and upsert.

    Writes one cvm_ingest_log row (integrity rule 3) via ``ingest_log.audited``:
    ``ok`` on success, ``error`` on an unexpected failure, or ``skipped`` when
    Apify never returned a dataset (403 actor-not-approved, 403 usage hard limit,
    408 run-timeout-exceeded, wait-budget miss, platform ABORTED). The audit
    writes are best-effort and never mask the ingest outcome.
    """

    async def work() -> ingest_log.Outcome | int:
        try:
            rows = await asyncio.to_thread(_scrape_and_upsert, conn, tickers)
            return rows
        except ApifyScrapeUnavailableError as exc:
            # No dataset was delivered.  Log loudly for the GitHub Actions
            # annotation, record a ``skipped`` audit row, and do not fail the
            # daily run — a usage-limit day must not skip ANALYZE and analytics.
            msg = ingest_log.describe(exc)
            logger.error(
                "ETF market scrape skipped — Apify did not return a dataset: %s", exc
            )
            print(f"::warning title=ETF scrape skipped::{exc}", flush=True, file=sys.stderr)
            return ingest_log.Outcome(0, "skipped", msg)

    return await ingest_log.audited(
        conn, LOG_ENTITY, LOG_DOC_TYPE, work, upsert=upsert_rows
    )


def _scrape_and_upsert(conn, tickers: Optional[List[str]] = None) -> int:
    tickers = tickers or _active_tickers(conn)
    if not tickers:
        raise RuntimeError(
            "No ETF tickers to scrape — seed cvm_etf_registry first (ingest_etf_registry)"
        )
    records = ApifyETFFetcher().fetch(tickers)
    snapshot = datetime.now(timezone.utc).date().isoformat()  # UTC: CI runs in UTC

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
    return await ingest_etf_market(conn)


if __name__ == "__main__":
    print("etf_market snapshots upserted:", asyncio.run(_run()))
