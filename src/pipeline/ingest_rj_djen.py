"""Daily RJ discovery from DJEN (#846): new recuperação cases and their published acts.

    python -m src.pipeline.ingest_rj_djen                       # the last RJ_DJEN_DAYS days, 27 state courts
    python -m src.pipeline.ingest_rj_djen --start 2026-09-01 --end 2026-09-30 --tribunal TJSC

Needs ``BR_PROXY_URL`` (DJEN refuses non-Brazilian egress, #843).

Per tribunal and day, every communication of class 129 / 128 becomes:

* an ``rj_case`` row with ``source = 'djen'``: the 20-digit number, the court
  division, the class, and ``devedor_nome`` = the names DJEN lists in polo
  ativo (the recuperanda), as printed and joined with "; ". Nothing inferred.
* an ``rj_document`` row for the act itself (DJEN's ``link``), ``titulo`` =
  "<tipoComunicacao>: <tipoDocumento>", ``found_on`` = its certidão URL and
  ``data_publicacao`` = the day DJEN made it available. ``tipo`` comes from the
  same title rules as the AJ sites, read on the act type plus the first lines of
  its text; the text itself is never stored. ``http_status`` stays NULL until
  the budgeted HEAD check reaches the link.

One ``cvm_ingest_log`` row per tribunal per run (entity ``rj``, doc_type
``djen:<TJ>``), period = the window's start month. A tribunal whose request
fails is an ``error`` row and the run ends red after every tribunal ran.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.fetchers.rj.djen import STATE_COURTS, DjenClient, DjenItem, certidao_url
from src.fetchers.rj.parse import classify_tipo
from src.pipeline.ingest_log import Outcome, audited
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

ENTITY = "rj"
SOURCE = "djen"


def _days(start: date, end: date) -> List[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def rows_for(items: Sequence[DjenItem], seen_at: datetime) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """rj_case and rj_document rows for one tribunal's items. Pure, so it is tested offline."""
    cases: Dict[str, Dict[str, Any]] = {}
    docs: List[Dict[str, Any]] = []
    for it in items:
        case = cases.setdefault(it.numero_processo, {
            "numero_processo": it.numero_processo, "source": SOURCE, "tribunal": it.tribunal,
            "vara": it.orgao, "classe": it.classe, "devedor_nome": None,
            "aj_name": None, "aj_case_url": None, "last_seen_at": seen_at,
        })
        if it.polo_ativo and not case["devedor_nome"]:
            case["devedor_nome"] = "; ".join(dict.fromkeys(it.polo_ativo))
        if not (it.link and it.link.startswith(("http://", "https://")) and it.hash):
            continue  # an act without its own link is a case signal only, never a document
        titulo = ": ".join(p for p in (it.tipo_comunicacao, it.tipo_documento) if p)
        docs.append({
            "numero_processo": it.numero_processo, "url": it.link,
            "tipo": classify_tipo(titulo, it.texto[:400]),
            "titulo": titulo or None, "source": SOURCE, "found_on": certidao_url(it.hash),
            "data_publicacao": (it.data_disponibilizacao or "")[:10] or None,
            "last_seen_at": seen_at,
        })
    return list(cases.values()), docs


class DjenIngestor:
    def __init__(self, pg: Any = None, client_factory=DjenClient) -> None:
        self._pg = pg or get_pg_client()
        self._client_factory = client_factory
        self._head_budget = max(int(os.environ.get("RJ_HEAD_BUDGET", "300") or 300), 0)

    def _unchecked(self, tribunal: str, limit: int) -> List[tuple]:
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT d.numero_processo, d.url FROM rj_document d JOIN rj_case c "
                "ON c.numero_processo = d.numero_processo AND c.source = d.source "
                "WHERE d.source = %s AND c.tribunal = %s AND d.http_status IS NULL "
                "ORDER BY random() LIMIT %s",
                (SOURCE, tribunal, limit),
            )
            return list(cur.fetchall())

    def _collect_sync(self, tribunal: str, days: Sequence[date], seen_at: datetime) -> Outcome:
        client = self._client_factory()
        try:
            items: List[DjenItem] = []
            for d in days:
                items.extend(client.day(tribunal, d))  # raises DjenError: the row is error
            cases, docs = rows_for(items, seen_at)
            rows = upsert_rows(self._pg, "rj_case", cases, conflict_columns="numero_processo,source")
            rows += upsert_rows(self._pg, "rj_document", docs, conflict_columns="numero_processo,url")
            # The links come from DJEN itself; each is still fetched before it counts as live.
            checked = [(client.status(url), n, url) for n, url in self._unchecked(tribunal, self._head_budget)]
        finally:
            client.close()
        answered = [c for c in checked if c[0] is not None]
        if answered:
            with self._pg.cursor() as cur:
                cur.executemany(
                    "UPDATE rj_document SET http_status = %s WHERE numero_processo = %s AND url = %s", answered)
        return Outcome(rows, error=(f"days={len(days)} items={len(items)} cases={len(cases)} "
                                    f"documents={len(docs)} checked={len(answered)}"))

    async def collect(self, tribunals: Sequence[str], start: date, end: date) -> Dict[str, int]:
        days = _days(start, end)
        seen_at = datetime.now(timezone.utc)
        results: Dict[str, int] = {}
        failures: List[str] = []
        for t in tribunals:  # one tribunal at a time: one Brazilian proxy, one request a second
            try:
                results[t] = await audited(
                    self._pg, ENTITY, f"{SOURCE}:{t}",
                    lambda t=t: asyncio.to_thread(self._collect_sync, t, days, seen_at),
                    period_year=start.year, period_month=start.month)
            except Exception as e:  # recorded by audited(); re-raised after every tribunal ran
                failures.append(f"{t}: {type(e).__name__}: {e}")
        if failures:
            raise RuntimeError(f"{len(failures)} of {len(tribunals)} DJEN tribunals failed: " + " | ".join(failures))
        return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RJ discovery from DJEN (#846).")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--tribunal", action="append", help="siglaTribunal; repeatable; default all 27")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    end = args.end or date.today() - timedelta(days=1)
    start = args.start or end - timedelta(days=max(int(os.environ.get("RJ_DJEN_DAYS", "3")), 1) - 1)
    if start > end:
        parser.error("start is after end")
    tribunals = args.tribunal or list(STATE_COURTS)
    unknown = set(tribunals) - set(STATE_COURTS)
    if unknown:
        parser.error(f"unknown tribunal(s): {sorted(unknown)}")
    results = asyncio.run(DjenIngestor().collect(tribunals, start, end))
    logger.info("DJEN %s..%s: %s", start, end, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
