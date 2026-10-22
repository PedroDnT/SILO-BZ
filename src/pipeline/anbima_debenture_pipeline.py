"""Capture ANBIMA's public debenture, CRI and CRA pages for a list of codes.

For each code it reads up to three pages of data.anbima.com.br: the
characteristics, the event agenda and the last-5-sessions indicative prices.
``--asset debentures`` (#1006) reads /debentures into ``anbima_debenture*``;
``--asset cri_cra`` (#1014) reads /certificado-de-recebiveis into
``anbima_cri_cra*``. Every page read writes one capture row first, then its
parsed rows. The whole run is one ``cvm_ingest_log`` row (anbima/<asset>).

A page that does not load or does not parse never stops the other pages, but
the run then ends as an error with the rows that did land, so a partial run is
never read as complete. Raw text is kept only for a parse failure.

Not wired into the daily run: the owner approves that after a green manual run
and after confirming the ANBIMA permission covers automated collection.

    python -m src.pipeline.anbima_debenture_pipeline --codes CGOSA2,AESLA8
    python -m src.pipeline.anbima_debenture_pipeline --codes CGOSA2 --dry-run
    python -m src.pipeline.anbima_debenture_pipeline --asset cri_cra --codes CRA019001E7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Callable, Iterable, Optional

from src.fetchers.anbima_debenture_fetcher import (
    BASE_URL, CRI_CRA_BASE_URL, PAGES, AnbimaDebentureFetcher,
)
from src.parsers import anbima_cri_cra as C
from src.parsers import anbima_debenture as P
from src.pipeline import ingest_log
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Asset:
    doc_type: str            # cvm_ingest_log doc_type under entity 'anbima'
    base_url: str
    ready_selector: str      # what the characteristics page shows once rendered
    capture_table: str
    targets: dict            # page → (table, conflict key, parser)


ASSETS = {
    "debentures": Asset("debentures", BASE_URL, "text=CNPJ", "anbima_debenture_capture", {
        "caracteristicas": ("anbima_debenture", "codigo", lambda c: [P.parse_caracteristicas(c)]),
        "agenda": ("anbima_debenture_event", "codigo,data_evento,evento", P.parse_agenda),
        "precos": ("anbima_debenture_indicative", "codigo,data_referencia", P.parse_precos),
    }),
    "cri_cra": Asset("cri_cra", CRI_CRA_BASE_URL, "text=CONDIÇÕES GERAIS DA EMISSÃO",
                     "anbima_cri_cra_capture", {
        "caracteristicas": ("anbima_cri_cra", "codigo", lambda c: [C.parse_caracteristicas(c)]),
        "agenda": ("anbima_cri_cra_event", "codigo,data_evento,evento", C.parse_agenda),
        "precos": ("anbima_cri_cra_indicative", "codigo,data_referencia", C.parse_precos),
    }),
}
CAPTURE_TABLE = ASSETS["debentures"].capture_table
TARGETS = ASSETS["debentures"].targets


def fetcher_for(asset: Asset) -> Callable[[], AnbimaDebentureFetcher]:
    return partial(AnbimaDebentureFetcher, base_url=asset.base_url,
                   ready_selector=asset.ready_selector)


def parse_codes(text: str) -> list[str]:
    codes = [c.strip().upper() for c in text.split(",") if c.strip()]
    bad = [c for c in codes if not c.isalnum()]
    if not codes or bad:
        raise ValueError(f"--codes needs comma-separated ANBIMA codes; bad: {bad}")
    return list(dict.fromkeys(codes))


class AnbimaDebentureIngestor:
    def __init__(self, conn=None, fetcher_factory: Optional[Callable[[], AnbimaDebentureFetcher]] = None,
                 asset: str = "debentures"):
        self.asset = ASSETS[asset]
        self.conn = conn if conn is not None else get_pg_client()
        self.fetcher_factory = fetcher_factory or fetcher_for(self.asset)

    async def ingest(self, codes: Iterable[str], pages: Iterable[str] = PAGES) -> int:
        codes, pages = list(codes), list(pages)
        capture_id = str(uuid.uuid4())  # the audit run id, never an asset id

        async def work() -> int:
            status: Counter = Counter()
            landed = 0
            async with self.fetcher_factory() as fetcher:
                async def one(code: str, page: str) -> None:
                    nonlocal landed
                    s, n = await self._page(fetcher, capture_id, code, page)
                    status[s] += 1
                    landed += n
                results = await asyncio.gather(*(one(c, p) for c in codes for p in pages),
                                               return_exceptions=True)
            # A database error is not a page failure: it ends the run at once,
            # with the rows that did land.
            errors = [r for r in results if isinstance(r, BaseException)]
            if errors:
                raise ingest_log.PartialIngestError(
                    f"ANBIMA {self.asset.doc_type}: write failed: {ingest_log.describe(errors[0])}",
                    rows=landed,
                ) from errors[0]
            failed = status["fetch_error"] + status["parse_error"]
            summary = ", ".join(f"{k}={v}" for k, v in sorted(status.items()))
            logger.info("ANBIMA %s %s: %s, rows=%d", self.asset.doc_type, capture_id, summary, landed)
            if failed:
                raise ingest_log.PartialIngestError(
                    f"ANBIMA {self.asset.doc_type}: {failed} of {sum(status.values())} pages failed ({summary})",
                    rows=landed,
                )
            return landed

        return await ingest_log.audited(
            self.conn, "anbima", self.asset.doc_type, work, upsert=upsert_rows, run_id=capture_id,
        )

    async def _page(self, fetcher, capture_id: str, code: str, page: str) -> tuple[str, int]:
        table, key, parse = self.asset.targets[page]
        row = {"capture_id": capture_id, "codigo": code, "page": page, "rows_parsed": 0,
               "payload_sha256": None, "raw_text": None, "error": None}
        try:
            cap = await fetcher.fetch(code, page)
        except Exception as exc:  # noqa: BLE001 — recorded as fetch_error, run ends red
            row.update(status="fetch_error", error=ingest_log.describe(exc),
                       observed_at=datetime.now(timezone.utc),
                       source_url=f"{self.asset.base_url}/{code}/{page}")
            await asyncio.to_thread(self._write_capture, row)
            return row["status"], 0
        row.update(observed_at=cap.observed_at, source_url=cap.url, payload_sha256=cap.sha256)
        try:
            records = parse(cap)
        except P.AnbimaParseError as exc:
            row.update(status="parse_error", error=str(exc), raw_text=cap.text)
            await asyncio.to_thread(self._write_capture, row)
            return row["status"], 0
        # Evidence first: a capture row exists before any data row cites it.
        row.update(status="parsed" if records else "no_data", rows_parsed=len(records))
        await asyncio.to_thread(self._write_capture, row)
        for r in records:
            r.update(capture_id=capture_id, observed_at=cap.observed_at)
        n = await asyncio.to_thread(upsert_rows, self.conn, table, records, key) if records else 0
        return row["status"], n

    def _write_capture(self, row: dict) -> None:
        upsert_rows(self.conn, self.asset.capture_table, [row], conflict_columns="capture_id,codigo,page")


async def dry_run(codes: list[str], pages: list[str], asset: str = "debentures") -> dict:
    """Fetch and parse only: no database, no credentials."""
    out: dict = {}
    spec = ASSETS[asset]
    async with fetcher_for(spec)() as fetcher:
        for code in codes:
            for page in pages:
                cap = await fetcher.fetch(code, page)
                rows = spec.targets[page][2](cap)
                out.setdefault(code, {})[page] = {"rows": len(rows), "sha256": cap.sha256}
    return out


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--asset", choices=sorted(ASSETS), default="debentures",
                        help="debentures (default) or cri_cra")
    parser.add_argument("--codes", required=True, help="Comma-separated ANBIMA codes, e.g. CGOSA2,AESLA8")
    parser.add_argument("--pages", default=",".join(PAGES), help=f"Subset of {','.join(PAGES)}")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse only, no database")
    args = parser.parse_args(argv)
    codes = parse_codes(args.codes)
    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    if not pages or set(pages) - set(PAGES):
        raise SystemExit(f"--pages must be a subset of {PAGES}")
    logging.basicConfig(level=logging.INFO)
    if args.dry_run:
        print(json.dumps(asyncio.run(dry_run(codes, pages, args.asset)), indent=2))
    else:
        asyncio.run(AnbimaDebentureIngestor(asset=args.asset).ingest(codes, pages))


if __name__ == "__main__":
    main()
