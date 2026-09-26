"""FNET restatement diffs — download, pair and diff re-filed documents (B4, slice 1).

Design: docs/planning/DOCUMENTS.md (§4 tables, §5 pairing, §6 algorithm, §7
cadence, §11 decisions). Parsing and diffing are src/parsers/fnet_xml_diff.py;
fetching is ``FnetFetcher.download``. This module owns the QUEUE, the PAIRING
and the STATUS of every re-filing it looks at.

Scope (decision 3): FIDC informe mensal estruturado only —
``categoria = 'Informes Periódicos'`` and
``tipo_documento = 'Informe Mensal Estruturado'`` with a tipoFundo '2' link.

The queue is every in-scope document with ``versao > 1`` that has no
``compared`` pair row yet, newest delivery first, capped per run
(``FNET_DIFF_MAX_DOCS``, default 500). For each, the predecessor is found by
EXACTLY the group key ``api.fund_restatements`` states (analytical file 24):
same cnpjFundo LINK, categoria, tipo_documento, especie and reference_raw;
highest lower versao, greatest fnet_id on a tie. Nothing is matched by name.

Every queued document ends the run with a pair row, and the row says why
when there is no diff:

  unpairable_no_link       no cnpjFundo link yet (the fortnightly sweep has
                           not reached the fund); retried next run
  unpairable_no_reference  the register row has no reference text
  no_predecessor           no lower versao in the register (history starts
                           after v1; retried after a register backfill)
  body_not_xml             a body is not XML (e.g. a PDF)
  parse_error              a body did not parse, or has an unsupported root
  declared_mismatch        the XML's own CNPJ or reference disagrees with the
                           link or the register: the disagreement is the
                           finding, and the pair is not diffed
  compared                 diffed; n_changed = 0 is a clean re-upload

The declared CNPJ is compared against the link but is NEVER used as a link
(decision 4). Audit: one ``cvm_ingest_log`` row per run, entity ``fnet``,
doc_type ``diff``; a failed download raises after its retries and the run
logs ``error`` for what it did not finish.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from src.fetchers.fnet_fetcher import FnetFetcher
from src.parsers.fnet_xml_diff import DIFF_VERSION, ParsedBody, diff_bodies, parse_body, summarize
from src.pipeline.ingest_log import audited
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

BODY_TABLE = "fnet_document_body"
PAIR_TABLE = "fnet_document_pair"
DIFF_TABLE = "fnet_document_diff"
LOG_ENTITY = "fnet"
DOC_DIFF = "diff"
PAIR_RULE = "group_key_v1"

# Slice 1 (decision 3). FII mensal / trimestral are the second slice.
SCOPE_CATEGORIA = "Informes Periódicos"
SCOPE_TIPO_DOCUMENTO = "Informe Mensal Estruturado"
SCOPE_TIPO_FUNDO = "2"   # FNET's tipoFundo code for FIDC

_QUEUE_SQL = """
SELECT d.fnet_id, d.versao, d.categoria, d.tipo_documento, d.especie, d.reference_raw,
       l.filter_value AS cnpj
FROM fnet_document d
JOIN fnet_document_filter t
  ON t.fnet_id = d.fnet_id AND t.filter_name = 'tipoFundo' AND t.filter_value = %(tipo_fundo)s
LEFT JOIN fnet_document_filter l
  ON l.fnet_id = d.fnet_id AND l.filter_name = 'cnpjFundo'
LEFT JOIN fnet_document_pair p
  ON p.fnet_id = d.fnet_id AND p.status = 'compared'
WHERE d.versao > 1
  AND d.categoria = %(categoria)s
  AND d.tipo_documento = %(tipo_documento)s
  AND p.id IS NULL
  AND (%(since)s IS NULL OR d.delivered_at >= %(since)s)
ORDER BY d.delivered_at DESC, d.fnet_id DESC
LIMIT %(limit)s
"""

# The stated group key of api.fund_restatements (24_api_fnet.sql), verbatim
# in spirit: same LINK, same categoria / tipo / especie (NULL-safe), same
# reference text (plain =), highest lower versao, greatest fnet_id on a tie.
_PREDECESSOR_SQL = """
SELECT p.fnet_id
FROM fnet_document_filter pl
JOIN fnet_document p ON p.fnet_id = pl.fnet_id
WHERE pl.filter_name = 'cnpjFundo'
  AND pl.filter_value = %(cnpj)s
  AND p.versao < %(versao)s
  AND p.categoria      IS NOT DISTINCT FROM %(categoria)s
  AND p.tipo_documento IS NOT DISTINCT FROM %(tipo_documento)s
  AND p.especie        IS NOT DISTINCT FROM %(especie)s
  AND p.reference_raw = %(reference_raw)s
ORDER BY p.versao DESC, p.fnet_id DESC
LIMIT 1
"""

_BODY_SQL = """
SELECT fnet_id, sha256, canonical_sha256, parse_status, declared_cnpj, declared_reference_raw
FROM fnet_document_body WHERE fnet_id = %(fnet_id)s
"""


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        n = int(raw)
    except ValueError:
        return default
    return n if n >= minimum else default


class FnetDiffIncomplete(RuntimeError):
    """One or more queued documents failed; the rest were processed. ``rows``
    is what landed, so ``audited`` records it on the error row."""

    def __init__(self, message: str, rows: int = 0):
        super().__init__(message)
        self.rows = rows


class FnetDiffIngestor:
    """Work the re-filing queue: download both bodies, pair, diff, store.

    Example::

        ing = FnetDiffIngestor()
        await ing.run(max_docs=500)
    """

    def __init__(self, fetcher: Optional[FnetFetcher] = None) -> None:
        self._fetcher = fetcher or FnetFetcher()
        self._pg = get_pg_client()

    # ── queries ──────────────────────────────────────────────────────────

    def queue(self, limit: int, since: Optional[date] = None) -> List[Dict[str, Any]]:
        with self._pg.cursor() as cur:
            cur.execute(_QUEUE_SQL, {
                "tipo_fundo": SCOPE_TIPO_FUNDO, "categoria": SCOPE_CATEGORIA,
                "tipo_documento": SCOPE_TIPO_DOCUMENTO, "since": since, "limit": limit,
            })
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def predecessor(self, doc: Dict[str, Any]) -> Optional[int]:
        with self._pg.cursor() as cur:
            cur.execute(_PREDECESSOR_SQL, {
                "cnpj": doc["cnpj"], "versao": doc["versao"], "categoria": doc["categoria"],
                "tipo_documento": doc["tipo_documento"], "especie": doc["especie"],
                "reference_raw": doc["reference_raw"],
            })
            row = cur.fetchone()
            return int(row[0]) if row else None

    def held_body(self, fnet_id: int) -> Optional[Dict[str, Any]]:
        with self._pg.cursor() as cur:
            cur.execute(_BODY_SQL, {"fnet_id": fnet_id})
            row = cur.fetchone()
            if not row:
                return None
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

    # ── bodies ───────────────────────────────────────────────────────────

    async def body(self, fnet_id: int) -> Tuple[Dict[str, Any], Optional[ParsedBody]]:
        """The stored body row for ``fnet_id``, downloading and parsing it if
        not held. Returns ``(body_row, parsed)``; ``parsed`` is None when the
        body was already held (its hashes and status are in the row) — the
        diff then re-downloads only when it needs the leaves."""
        held = self.held_body(fnet_id)
        if held is not None:
            return held, None
        data, ctype, filename = await self._fetcher.download(fnet_id)
        parsed = parse_body(data, ctype)
        row = {
            "fnet_id": fnet_id,
            "content_type": ctype,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "canonical_sha256": parsed.canonical_sha256,
            "filename": filename,
            "root_element": parsed.root_element,
            "schema_version": parsed.schema_version,
            "declared_cnpj_raw": parsed.declared_cnpj_raw,
            "declared_reference_raw": parsed.declared_reference_raw,
            "declared_cnpj": parsed.declared_cnpj,
            "leaf_count": parsed.leaf_count if parsed.parse_status == "ok" else None,
            "parse_status": parsed.parse_status,
            "parse_error": parsed.error,
        }
        upsert_rows(self._pg, BODY_TABLE, [row], conflict_columns="fnet_id")
        return row, parsed

    async def parsed_body(self, fnet_id: int, cached: Optional[ParsedBody]) -> ParsedBody:
        """The leaves for a body: from the download just made, else a fresh
        download (bodies are not stored, decision 2)."""
        if cached is not None:
            return cached
        data, ctype, _ = await self._fetcher.download(fnet_id)
        return parse_body(data, ctype)

    # ── one document ─────────────────────────────────────────────────────

    def _pair_row(self, doc: Dict[str, Any], prev_id: Optional[int], status: str, **extra: Any) -> Dict[str, Any]:
        row = {
            "fnet_id": doc["fnet_id"], "prev_fnet_id": prev_id, "cnpj": doc["cnpj"],
            "pair_rule": PAIR_RULE, "status": status, "n_changed": None, "n_added": None,
            "n_removed": None, "identical_bytes": None, "identical_canonical": None,
            "diff_version": DIFF_VERSION,
        }
        row.update(extra)
        return row

    async def process(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Pair and diff one queued document. Returns the pair row stored."""
        if not doc["cnpj"]:
            return self._store_pair(self._pair_row(doc, None, "unpairable_no_link"))
        if not doc["reference_raw"]:
            return self._store_pair(self._pair_row(doc, None, "unpairable_no_reference"))
        prev_id = self.predecessor(doc)
        if prev_id is None:
            return self._store_pair(self._pair_row(doc, None, "no_predecessor"))

        new_row, new_parsed = await self.body(doc["fnet_id"])
        prev_row, prev_parsed = await self.body(prev_id)
        for r in (new_row, prev_row):
            if r["parse_status"] == "not_xml":
                return self._store_pair(self._pair_row(doc, prev_id, "body_not_xml"))
            if r["parse_status"] in ("parse_error", "unsupported_root"):
                return self._store_pair(self._pair_row(doc, prev_id, "parse_error"))
            # decision 4/5: the declared CNPJ is a CHECK, never a link
            if r["declared_cnpj"] is not None and r["declared_cnpj"] != doc["cnpj"]:
                return self._store_pair(self._pair_row(doc, prev_id, "declared_mismatch"))
            if (r["declared_reference_raw"] or "").strip() != (doc["reference_raw"] or "").strip():
                return self._store_pair(self._pair_row(doc, prev_id, "declared_mismatch"))

        identical_bytes = new_row["sha256"] == prev_row["sha256"]
        identical_canonical = new_row["canonical_sha256"] == prev_row["canonical_sha256"]
        if identical_canonical:
            rows: List[Dict[str, Any]] = []
        else:
            new_p = await self.parsed_body(doc["fnet_id"], new_parsed)
            prev_p = await self.parsed_body(prev_id, prev_parsed)
            rows = diff_bodies(prev_p, new_p)
            for r in rows:
                r["fnet_id"] = doc["fnet_id"]
                r["prev_fnet_id"] = prev_id
            if rows:
                upsert_rows(self._pg, DIFF_TABLE, rows, conflict_columns="fnet_id,prev_fnet_id,field_path")
        counts = summarize(rows)
        return self._store_pair(self._pair_row(
            doc, prev_id, "compared", identical_bytes=identical_bytes,
            identical_canonical=identical_canonical, **counts))

    def _store_pair(self, row: Dict[str, Any]) -> Dict[str, Any]:
        upsert_rows(self._pg, PAIR_TABLE, [row], conflict_columns="fnet_id,prev_fnet_id")
        if row["status"] == "compared":
            # The earlier "why not" rows for this document (no link yet, no
            # predecessor yet) are superseded by the comparison: one row per
            # re-filing is what fund_restatements reads.
            with self._pg.cursor() as cur:
                cur.execute("DELETE FROM fnet_document_pair WHERE fnet_id = %s AND status <> 'compared'",
                            (row["fnet_id"],))
        return row

    # ── orchestration ────────────────────────────────────────────────────

    async def work(self, max_docs: int, since: Optional[date] = None) -> int:
        """Process up to ``max_docs`` queued documents. Returns diff rows +
        pair rows stored. A document whose download fails does not stop the
        rest; the run then raises ``FnetDiffIncomplete`` naming each one."""
        docs = self.queue(max_docs, since)
        stored = 0
        failed: List[str] = []
        by_status: Dict[str, int] = {}
        for doc in docs:
            try:
                pair = await self.process(doc)
            except Exception as exc:  # re-raised below, after the other documents
                logger.error("FNET diff fnet_id=%s failed: %r; continuing", doc["fnet_id"], exc)
                failed.append(f"{doc['fnet_id']}: {exc!r}")
                continue
            by_status[pair["status"]] = by_status.get(pair["status"], 0) + 1
            stored += 1 + sum(v for k, v in pair.items() if k in ("n_changed", "n_added", "n_removed") and v)
        logger.info("FNET diff: %d queued, statuses %s, %d failed", len(docs), by_status, len(failed))
        if failed:
            raise FnetDiffIncomplete(
                f"FNET diff: {len(failed)} of {len(docs)} document(s) failed ({stored} rows stored from the rest). "
                + "; ".join(failed), rows=stored)
        return stored

    async def run(self, max_docs: Optional[int] = None, since: Optional[date] = None) -> Dict[str, int]:
        """The audited entry point: one cvm_ingest_log row (fnet / diff)."""
        cap = max_docs if max_docs is not None else _env_int("FNET_DIFF_MAX_DOCS", 500)
        today = date.today()
        n = await audited(
            self._pg, LOG_ENTITY, DOC_DIFF, lambda: self.work(cap, since),
            period_year=today.year, period_month=today.month, upsert=upsert_rows,
        )
        return {DIFF_TABLE: n}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    totals = await FnetDiffIngestor().run()
    logger.info("FNET diff done: %s", totals)


if __name__ == "__main__":
    asyncio.run(_main())
