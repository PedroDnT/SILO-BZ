"""FNET restatement diffs: what a fund changed between versions (backlog B4, slice 1).

The design and Pedro's decisions of 2026-09-26 are docs/planning/DOCUMENTS.md.
Fetching is ``FnetFetcher.download``; parsing and the diff are
src/parsers/fnet_xml.py; the tables are migration 46.

The queue is derived, never stored: every FIDC informe mensal in the register
(``fnet_document``, tipoFundo link 2) with ``versao`` > 1, delivered in the
window, that has no terminal pair row at the current ``DIFF_VERSION``. Each is
paired with its predecessor by ``api.fund_restatements``' own group key
(analytical 24: same cnpjFundo link, categoria, tipo_documento, especie and
reference_raw; highest lower versao, greatest fnet_id on a tie), so a diff pair
is always a row that function already serves.

* A document that cannot be paired yet (no cnpjFundo link: the fortnightly
  sweep has not reached its fund; no reference; no lower version in the
  register) gets a pair row saying so, costs no download, and is re-tried on
  every run.
* A pairable one downloads both bodies (1 request/s, the fetcher's pace) and
  gets one terminal pair row: ``compared`` with its diff rows, or why not
  (``body_not_xml``, ``parse_error``, ``unsupported_root``,
  ``declared_mismatch``, ``body_hash_mismatch``).
* Raw XML is not kept (decision 2 (b)). A body already stored whose re-fetch
  hashes differently is a finding: logged, the stored row kept, the pair
  ``body_hash_mismatch``. It is never overwritten.
* Each run is capped (``--max-docs``, ``FNET_DIFF_MAX_DOCS``, default 200) and
  time-budgeted (``--budget-minutes``, ``FNET_DIFF_BUDGET_MINUTES``, default
  30), newest restatement group first. What the cap or budget leaves stays in
  the queue for the next run, and the log says how many.
* A failed download does not abandon the rest: the run moves on, then raises
  ``FnetDiffIncomplete`` naming every failure, so the audit row is ``error``.
  Three failures in a row stop the run early (FNET down is not 200 timeouts).

One ``cvm_ingest_log`` row per run, entity ``fnet``, doc_type ``diff``, period
= the window's start month.

    python -m src.pipeline.fnet_diff                       # daily: 2026-01-01..today
    python -m src.pipeline.fnet_diff --from 2026-01-01 --to 2026-06-30 --max-docs 0
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.fetchers.fnet_fetcher import FnetFetcher
from src.parsers import fnet_xml
from src.pipeline.ingest_log import audited
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

LOG_ENTITY = "fnet"
DOC_DIFF = "diff"
BODY_TABLE = "fnet_document_body"
PAIR_TABLE = "fnet_document_pair"
DIFF_TABLE = "fnet_document_diff"
BODY_CONFLICT = "fnet_id"
PAIR_CONFLICT = "fnet_id,prev_fnet_id"
DIFF_CONFLICT = "fnet_id,prev_fnet_id,field_path"
PAIR_RULE = "group_key_v1"

# Slice 1: the FIDC informe mensal. FNET's label as the register stores it
# (``_clean`` strips its trailing space) and the tipoFundo link 2 = FIDC.
TIPO_DOCUMENTO = "Informe Mensal Estruturado"
TIPO_FUNDO = "2"

# Decision 6: 2026 only for now; older years are OPEN_ITEMS.md row 2f.
DEFAULT_FROM = date(2026, 1, 1)
DEFAULT_MAX_DOCS = 200
DEFAULT_BUDGET_MINUTES = 30.0
MAX_CONSECUTIVE_FAILURES = 3
# Parsed bodies kept in memory: the queue runs a group's versions together,
# newest first, so v3's predecessor is v2's own body a moment later.
_CACHE_SIZE = 32

# Outcomes that need no download; re-evaluated on every run.
WAITING = ("unpairable_no_link", "unpairable_no_reference", "no_predecessor")
# Outcomes that take a document off the queue for this DIFF_VERSION.
TERMINAL = ("compared", "body_not_xml", "parse_error", "unsupported_root",
            "declared_mismatch", "body_hash_mismatch")

_QUEUE_SQL = """
WITH cand AS (
    SELECT d.fnet_id, l.filter_value AS cnpj, d.categoria, d.tipo_documento,
           d.especie, d.reference_raw, d.versao, d.delivered_at
    FROM fnet_document d
    JOIN fnet_document_filter t
      ON t.fnet_id = d.fnet_id
     AND t.filter_name = 'tipoFundo'
     AND t.filter_value = %(tipo_fundo)s
    LEFT JOIN fnet_document_filter l
      ON l.fnet_id = d.fnet_id
     AND l.filter_name = 'cnpjFundo'
    WHERE d.versao > 1
      AND d.tipo_documento = %(tipo_documento)s
      AND d.delivered_at >= %(start)s
      AND d.delivered_at < %(stop)s
      AND NOT EXISTS (
          SELECT 1 FROM fnet_document_pair p
          WHERE p.fnet_id = d.fnet_id
            AND p.diff_version = %(diff_version)s
            AND p.status = ANY(%(terminal)s))
)
SELECT c.fnet_id, c.cnpj, c.reference_raw, c.versao, c.delivered_at,
       pv.fnet_id AS prev_fnet_id
FROM cand c
-- api.fund_restatements' pairing, verbatim (analytical 24): an unlinked
-- document (cnpj NULL) makes the join empty rather than being grouped by name.
LEFT JOIN LATERAL (
    SELECT p.fnet_id
    FROM fnet_document_filter pl
    JOIN fnet_document p ON p.fnet_id = pl.fnet_id
    WHERE pl.filter_name = 'cnpjFundo'
      AND pl.filter_value = c.cnpj
      AND p.versao < c.versao
      AND p.categoria      IS NOT DISTINCT FROM c.categoria
      AND p.tipo_documento IS NOT DISTINCT FROM c.tipo_documento
      AND p.especie        IS NOT DISTINCT FROM c.especie
      AND p.reference_raw = c.reference_raw
    ORDER BY p.versao DESC, p.fnet_id DESC
    LIMIT 1
) pv ON TRUE
ORDER BY max(c.delivered_at) OVER (
             PARTITION BY c.cnpj, c.categoria, c.especie, c.reference_raw) DESC,
         c.cnpj, c.reference_raw, c.versao DESC, c.fnet_id DESC
"""


class FnetDiffIncomplete(RuntimeError):
    """One or more documents failed; the run's audit row is ``error``.

    ``rows`` is what the run stored before and after the failures, recorded by
    ``audited`` as ``rows_upserted``.
    """

    def __init__(self, message: str, rows: int = 0):
        super().__init__(message)
        self.rows = rows


@dataclass(frozen=True)
class Body:
    """One downloaded body: its parse, its byte hash, and a hash disagreement if any."""

    parsed: fnet_xml.ParsedBody
    sha256: str
    mismatch: Optional[str] = None


def judge(cnpj: str, reference_raw: str, new: Body, prev: Body) -> Tuple[str, Optional[str], List[dict]]:
    """The pair's status, why (for anything but ``compared``), and its diff rows. Pure."""
    sides = (("new", new), ("previous", prev))
    for name, b in sides:
        if b.mismatch:
            return "body_hash_mismatch", f"{name}: {b.mismatch}", []
    for status, parse_status in (("body_not_xml", fnet_xml.NOT_XML),
                                 ("parse_error", fnet_xml.PARSE_ERROR),
                                 ("unsupported_root", fnet_xml.UNSUPPORTED_ROOT)):
        for name, b in sides:
            if b.parsed.parse_status == parse_status:
                why = b.parsed.error or f"root {b.parsed.root_element!r}"
                return status, f"{name}: {why}", []
    for name, b in sides:
        why = fnet_xml.declared_mismatch(b.parsed, cnpj, reference_raw)
        if why:
            return "declared_mismatch", f"{name}: {why}", []
    return "compared", None, fnet_xml.diff_bodies(prev.parsed, new.parsed)


def _body_row(fnet_id: int, content: bytes, ctype: Optional[str], filename: Optional[str],
              sha: str, p: fnet_xml.ParsedBody) -> Dict[str, Any]:
    # fetched_at is left to its default: the first fetch. A re-fetch of the
    # same bytes then changes nothing, and upsert_rows rewrites nothing.
    return {
        "fnet_id": fnet_id,
        "content_type": ctype,
        "bytes": len(content),
        "sha256": sha,
        "canonical_sha256": p.canonical_sha256,
        "filename": filename,
        "root_element": p.root_element,
        "schema_version": p.schema_version,
        "declared_cnpj_raw": p.declared_cnpj_raw,
        "declared_cnpj": p.declared_cnpj,
        "declared_reference_raw": p.declared_reference_raw,
        "leaf_count": p.leaf_count,
        "parse_status": p.parse_status,
        "parse_error": p.error if not p.ok else None,
    }


def _pair_row(cand: Dict[str, Any], status: str, **cols: Any) -> Dict[str, Any]:
    row = {
        "fnet_id": cand["fnet_id"],
        "prev_fnet_id": cand.get("prev_fnet_id") if status not in WAITING else None,
        "cnpj": cand["cnpj"],
        "pair_rule": PAIR_RULE,
        "status": status,
        "detail": None,
        "n_changed": None,
        "n_added": None,
        "n_removed": None,
        "identical_bytes": None,
        "identical_canonical": None,
        "diff_version": fnet_xml.DIFF_VERSION,
    }
    row.update(cols)
    return row


class FnetDiffIngestor:
    """Work the restatement queue for one delivery window.

    Example::

        ing = FnetDiffIngestor(max_docs=200, budget_minutes=30)
        await ing.update(date(2026, 1, 1), date.today())
    """

    def __init__(
        self,
        fetcher: Optional[FnetFetcher] = None,
        *,
        max_docs: int = DEFAULT_MAX_DOCS,
        budget_minutes: float = DEFAULT_BUDGET_MINUTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher or FnetFetcher()
        self._pg = get_pg_client()
        self._max_docs = max_docs          # 0 = no cap
        self._budget = budget_minutes * 60
        self._clock = clock
        self._cache: "OrderedDict[int, Body]" = OrderedDict()
        self._stored = 0

    # ── storage ──────────────────────────────────────────────────────────

    def queue(self, start: date, end: date) -> List[Dict[str, Any]]:
        params = {
            "tipo_fundo": TIPO_FUNDO,
            "tipo_documento": TIPO_DOCUMENTO,
            "start": start,
            "stop": end + timedelta(days=1),
            "diff_version": fnet_xml.DIFF_VERSION,
            "terminal": list(TERMINAL),
        }
        with self._pg.cursor() as cur:
            cur.execute(_QUEUE_SQL, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _upsert(self, table: str, rows: List[Dict[str, Any]], conflict: str) -> None:
        self._stored += upsert_rows(self._pg, table, rows, conflict_columns=conflict)

    def _stored_sha(self, fnet_id: int) -> Optional[Tuple[str, Optional[str]]]:
        with self._pg.cursor() as cur:
            cur.execute("SELECT sha256, canonical_sha256 FROM fnet_document_body WHERE fnet_id = %s",
                        (fnet_id,))
            return cur.fetchone()

    def _clear(self, fnet_ids: Sequence[int], keep_prev: Optional[int]) -> None:
        """Drop a document's pair row for any OTHER predecessor, and all its diff rows.

        A document holds exactly one pair row: its latest outcome. Its diff
        rows are rewritten whole, so a field that stopped differing (a new
        diff_version) does not linger.
        """
        with self._pg.cursor() as cur:
            cur.execute(
                "DELETE FROM fnet_document_pair WHERE fnet_id = ANY(%s) "
                "AND prev_fnet_id IS DISTINCT FROM %s",
                (list(fnet_ids), keep_prev))
            cur.execute("DELETE FROM fnet_document_diff WHERE fnet_id = ANY(%s)", (list(fnet_ids),))

    # ── one document ─────────────────────────────────────────────────────

    async def _body(self, http: Any, fnet_id: int) -> Body:
        if fnet_id in self._cache:
            self._cache.move_to_end(fnet_id)
            return self._cache[fnet_id]
        content, ctype, filename = await self._fetcher.download(http, fnet_id)
        sha = hashlib.sha256(content).hexdigest()
        parsed = fnet_xml.parse_body(content, ctype)
        stored = self._stored_sha(fnet_id)
        mismatch = None
        if stored is not None and stored[0] != sha:
            same = "same" if stored[1] is not None and stored[1] == parsed.canonical_sha256 else "different"
            mismatch = (f"body {fnet_id} re-fetched with sha256 {sha}, stored {stored[0]} "
                        f"({same} canonical content)")
            logger.error("FNET diff: %s; the stored body row is kept", mismatch)
        else:
            self._upsert(BODY_TABLE, [_body_row(fnet_id, content, ctype, filename, sha, parsed)], BODY_CONFLICT)
        body = Body(parsed, sha, mismatch)
        self._cache[fnet_id] = body
        while len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return body

    async def compare(self, http: Any, cand: Dict[str, Any]) -> str:
        """Download, judge and store one pairable document. Returns its status."""
        new = await self._body(http, cand["fnet_id"])
        prev = await self._body(http, cand["prev_fnet_id"])
        status, detail, diffs = judge(cand["cnpj"], cand["reference_raw"], new, prev)
        cols: Dict[str, Any] = {"detail": detail, "compared_at": datetime.now(timezone.utc)}
        if status == "compared":
            cols.update(fnet_xml.summarize(diffs))
            cols["identical_bytes"] = new.sha256 == prev.sha256
            cols["identical_canonical"] = new.parsed.canonical_sha256 == prev.parsed.canonical_sha256
        self._clear([cand["fnet_id"]], cand["prev_fnet_id"])
        for r in diffs:
            r.update(fnet_id=cand["fnet_id"], prev_fnet_id=cand["prev_fnet_id"],
                     diff_version=fnet_xml.DIFF_VERSION)
        self._upsert(DIFF_TABLE, diffs, DIFF_CONFLICT)
        # The pair row last: until it lands the document stays in the queue.
        self._upsert(PAIR_TABLE, [_pair_row(cand, status, **cols)], PAIR_CONFLICT)
        return status

    # ── the run ──────────────────────────────────────────────────────────

    async def run(self, start: date, end: date) -> int:
        """Work the queue for delivery days ``start..end``. Returns rows stored."""
        self._stored = 0
        waiting: List[Dict[str, Any]] = []
        work: List[Dict[str, Any]] = []
        links: Dict[int, str] = {}
        for c in self.queue(start, end):
            if c["fnet_id"] in links:
                # Linked to two funds (never observed): paired once, on the first link.
                logger.warning("FNET diff: document %s is linked to %s and %s; paired on %s only",
                               c["fnet_id"], links[c["fnet_id"]], c["cnpj"], links[c["fnet_id"]])
                continue
            links[c["fnet_id"]] = c["cnpj"]
            if c["cnpj"] is None:
                waiting.append(_pair_row(c, "unpairable_no_link"))
            elif not c["reference_raw"]:
                waiting.append(_pair_row(c, "unpairable_no_reference"))
            elif c["prev_fnet_id"] is None:
                waiting.append(_pair_row(c, "no_predecessor"))
            else:
                work.append(c)
        if waiting:
            # No compared_at: an unchanged wait rewrites nothing on the next run.
            self._clear([w["fnet_id"] for w in waiting], None)
            self._upsert(PAIR_TABLE, waiting, PAIR_CONFLICT)

        todo = work[: self._max_docs] if self._max_docs else work
        deadline = self._clock() + self._budget
        statuses: Dict[str, int] = {}
        failed: List[str] = []
        streak = 0
        done = 0
        async with self._fetcher.client() as http:
            for c in todo:
                if self._clock() >= deadline:
                    logger.warning("FNET diff: the %.0f-minute budget is spent", self._budget / 60)
                    break
                try:
                    status = await self.compare(http, c)
                except Exception as exc:  # re-raised below, after the other documents
                    failed.append(f"{c['fnet_id']}: {exc!r}")
                    streak += 1
                    logger.error("FNET diff %s (prev %s) failed: %r", c["fnet_id"], c["prev_fnet_id"], exc)
                    if streak >= MAX_CONSECUTIVE_FAILURES:
                        logger.error("FNET diff: %d failures in a row; stopping this run", streak)
                        break
                    continue
                streak = 0
                done += 1
                statuses[status] = statuses.get(status, 0) + 1
        left = len(work) - done
        logger.info(
            "FNET diff %s..%s: %d waiting (%s), %d pairable, %d judged %s, %d failed, %d left in the queue",
            start, end, len(waiting),
            ", ".join(f"{s} {sum(1 for w in waiting if w['status'] == s)}" for s in WAITING),
            len(work), done, statuses, len(failed), left)
        if failed:
            raise FnetDiffIncomplete(
                f"FNET diff {start}..{end}: {len(failed)} document(s) failed "
                f"({self._stored} rows stored from the rest; {left} left in the queue). " + "; ".join(failed),
                rows=self._stored,
            )
        return self._stored

    async def update(self, start: date, end: date) -> int:
        """``run`` under its one audit row (entity fnet, doc_type diff)."""
        return await audited(
            self._pg, LOG_ENTITY, DOC_DIFF, lambda: self.run(start, end),
            period_year=start.year, period_month=start.month, upsert=upsert_rows,
        )


def _env_number(name: str, default: float, cast: Callable[[str], Any]) -> Any:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = cast(raw)  # a malformed setting raises: never run with a guessed one
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {raw!r}")
    return value


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.pipeline.fnet_diff",
                                description="FNET restatement diffs (FIDC informe mensal).")
    p.add_argument("--from", dest="start", type=date.fromisoformat,
                   help="first delivery day (default FNET_DIFF_FROM or 2026-01-01)")
    p.add_argument("--to", dest="end", type=date.fromisoformat, help="last delivery day (default today)")
    p.add_argument("--max-docs", type=int, help="documents to download-and-diff this run; 0 = no cap")
    p.add_argument("--budget-minutes", type=float, help="stop taking new documents after this long")
    return p.parse_args(argv)


async def _main(argv: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    start = args.start or date.fromisoformat(os.getenv("FNET_DIFF_FROM", "").strip() or DEFAULT_FROM.isoformat())
    end = args.end or date.today()
    if start > end:
        raise SystemExit(f"--from {start} is after --to {end}")
    max_docs = args.max_docs if args.max_docs is not None else _env_number(
        "FNET_DIFF_MAX_DOCS", DEFAULT_MAX_DOCS, int)
    budget = args.budget_minutes if args.budget_minutes is not None else _env_number(
        "FNET_DIFF_BUDGET_MINUTES", DEFAULT_BUDGET_MINUTES, float)
    if max_docs < 0 or budget <= 0:
        raise SystemExit("--max-docs must be >= 0 and --budget-minutes > 0")
    rows = await FnetDiffIngestor(max_docs=max_docs, budget_minutes=budget).update(start, end)
    logger.info("FNET diff done: %d rows stored", rows)


if __name__ == "__main__":
    asyncio.run(_main())
