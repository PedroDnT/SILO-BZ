"""Capture B3 OTC debentures with retrieval vintages and an honest date census.

Only complete captures are eligible for a research read. Partial writes and
clamped date ranges remain visible as incomplete; no date/price is filled.
Daily use is opt-in until the source export and deployment have been verified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.fetchers.b3_bdi_fetcher import B3BdiEmpty, B3BdiFetcher
from src.parsers import b3_credit as P
from src.parsers.b3_bdi import reconcile_span
from src.pipeline import ingest_log
from src.store.pg_client import _get_upsert_chunk_size, get_pg_client, upsert_rows

logger = logging.getLogger(__name__)
CAPTURE_TABLE = "b3_credit_capture"
FACT_TABLE = "fact_credit_market"
FACT_KEY = "capture_id,instrument_code,trade_date,settlement_date,trade_classification,metric"
MAX_RANGE_DAYS = 31


def yesterday() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=1)


def validate_range(start: date, end: date) -> None:
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError("ConsolidatedRecords needs an inclusive range of 1..31 calendar days")
    if end > yesterday():
        raise ValueError("ConsolidatedRecords needs completed days, no current/future session")


def known_sessions(conn, start: date, end: date) -> list[date]:
    """Equity tape is a reconciliation calendar, not proof OTC traded that day."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT trade_date FROM b3_cotahist
             WHERE tpmerc = '010' AND trade_date BETWEEN %s AND %s
             ORDER BY trade_date
        """, (start, end))
        return [r[0] for r in cur.fetchall()]


class B3CreditIngestor:
    def __init__(self, conn=None, fetcher=None):
        self.conn = conn if conn is not None else get_pg_client()
        # A first one-day export already exceeded 45 s during the source audit.
        # Keep attempts and the daily budget bounded; never call a timeout empty.
        self.fetcher = fetcher if fetcher is not None else B3BdiFetcher(
            timeout=120, max_retries=2, retry_delay=5,
        )

    async def ingest(self, start: date, end: date) -> int:
        validate_range(start, end)
        capture_id = str(uuid.uuid4())  # the audit run, not an invented asset ID

        async def work() -> int:
            expected = await asyncio.to_thread(known_sessions, self.conn, start, end)
            if not expected:
                raise RuntimeError("No COTAHIST sessions in range; cannot verify credit coverage")
            try:
                text = await self.fetcher.fetch_table(P.TABLE_NAME, start, end)
            except B3BdiEmpty as exc:
                raise RuntimeError(
                    "ConsolidatedRecords empty for known sessions; no-trade vs unavailable "
                    "history is unproven"
                ) from exc
            # Knowledge time is when this response arrived, NEVER the trade date.
            observed_at = datetime.now(timezone.utc)
            capture = {
                "capture_id": capture_id, "source": P.SOURCE,
                "requested_from": start, "requested_to": end,
                "observed_at": observed_at,
                "source_url": f"{self.fetcher.base_url}/bdi/table/export/csv?lang=pt-br",
                "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "raw_csv": text, "status": "captured",
                "expected_dates": [d.isoformat() for d in expected],
                "delivered_dates": [], "missing_dates": [d.isoformat() for d in expected],
                "source_rows": 0, "debenture_rows": 0, "dropped_rows": 0,
            }
            # Persist evidence before parsing: a layout change is recoverable.
            await asyncio.to_thread(upsert_rows, self.conn, CAPTURE_TABLE, [capture],
                                    conflict_columns="capture_id")
            parsed = P.parse(text, start, end)
            _, missing = reconcile_span(
                [{"date": d} for d in parsed.delivered_dates], "date", expected,
            )
            capture.update(
                delivered_dates=[d.isoformat() for d in parsed.delivered_dates],
                missing_dates=[d.isoformat() for d in missing],
                source_rows=parsed.source_rows, debenture_rows=len(parsed.rows),
                dropped_rows=parsed.dropped_rows,
            )
            records = P.facts(parsed, capture_id)
            n = 0
            try:
                # One pg_client statement per batch: if a later batch fails,
                # the audit includes every previously acknowledged write.
                batch_size = min(5000, _get_upsert_chunk_size())
                for offset in range(0, len(records), batch_size):
                    n += await asyncio.to_thread(
                        upsert_rows, self.conn, FACT_TABLE, records[offset:offset + batch_size],
                        conflict_columns=FACT_KEY,
                    )
                capture["status"] = "incomplete" if missing or parsed.dropped_rows else "complete"
                await asyncio.to_thread(upsert_rows, self.conn, CAPTURE_TABLE, [capture],
                                        conflict_columns="capture_id")
            except Exception as exc:
                # A capture cannot be read as complete before ALL facts landed.
                raise ingest_log.PartialIngestError(str(exc), rows=n) from exc
            if capture["status"] != "complete":
                raise ingest_log.PartialIngestError(
                    f"ConsolidatedRecords incomplete: missing sessions="
                    f"{','.join(d.isoformat() for d in missing) or 'none'}; "
                    f"dropped rows={parsed.dropped_rows}", rows=n,
                )
            return n

        return await ingest_log.audited(
            self.conn, "b3", "credit_consolidated", work,
            period_year=start.year, period_month=start.month,
            upsert=upsert_rows, run_id=capture_id,
        )

    async def daily_update(self) -> dict[str, int]:
        end = yesterday()
        return {FACT_TABLE: await self.ingest(end - timedelta(days=6), end)}

    async def backfill(self, start: date, end: date) -> dict[str, int]:
        if end < start or end > yesterday():
            raise ValueError("Backfill needs a past, ordered date range")
        # Bounded slices: the catalog's M-18 is not proof a huge request delivers
        # eighteen months. Stop at the first incomplete slice, keeping its audit.
        total = 0
        while start <= end:
            stop = min(start + timedelta(days=6), end)
            total += await self.ingest(start, stop)
            start = stop + timedelta(days=1)
        return {FACT_TABLE: total}


async def main(args: argparse.Namespace) -> None:
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    validate_range(start, end)
    if args.dry_run:
        # No database client or credentials used; verifies the public export.
        fetcher = B3BdiFetcher(timeout=120, max_retries=1)
        text = await fetcher.fetch_table(P.TABLE_NAME, start, end)
        parsed = P.parse(text, start, end)
        print(json.dumps({
            "source": P.SOURCE, "source_rows": parsed.source_rows,
            "debenture_rows": len(parsed.rows), "dropped_rows": parsed.dropped_rows,
            "delivered_dates": [d.isoformat() for d in parsed.delivered_dates],
            "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "calendar_reconciled": False,
        }))
        if parsed.dropped_rows:
            raise RuntimeError("Dry run dropped source rows")
    else:
        await B3CreditIngestor().ingest(start, end)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="First date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Last date, YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Fetch/parse only, no database")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args()))
