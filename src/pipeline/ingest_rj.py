"""Daily collector of RJ case document links from administrador judicial sites (#845).

    python -m src.pipeline.ingest_rj                 # every site in sites.SITES
    python -m src.pipeline.ingest_rj --site cataliseaj.com.br

For each site: read its case list pages, open every case page, keep the case
when the page shows a CNJ process number, and keep every document link on it.
Links only; no file is downloaded or stored.

Integrity (AGENTS.md):

* A list page that fails raises: the site's audit row is ``error`` and the run
  is red. A case page that fails is counted, named in the audit row, and the
  site ends ``error`` with the rows it did land; it is never skipped silently.
* A case page without a CNJ process number yields no case (a key is never
  synthesized); the count is in the audit row.
* Watchdog: a site that lists zero cases after it had cases stored raises. An
  empty list is a broken adapter until shown otherwise.
* New document links get a HEAD check, at most ``RJ_HEAD_BUDGET`` per site per
  run; ``http_status`` records the answer, and links not checked yet are
  checked on later runs. The link itself always comes from a fetched case page.
* One ``cvm_ingest_log`` row per site per run: entity ``rj``, doc_type the
  site's ``source``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.fetchers.rj.client import FetchError, PoliteClient, RobotsDisallowed
from src.fetchers.rj.parse import case_links, classify_tipo, parse_case_page
from src.fetchers.rj.sites import SITES, Site
from src.pipeline.ingest_log import Outcome, audited
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

ENTITY = "rj"
CONCURRENT_SITES = 8


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() else default


class EmptySiteError(RuntimeError):
    """The site listed no cases although cases from it are stored."""


@dataclass
class SiteHarvest:
    cases: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    case_pages: int = 0
    failed_pages: List[str] = field(default_factory=list)
    without_number: List[str] = field(default_factory=list)


def harvest_site(site: Site, client: PoliteClient, seen_at: datetime) -> SiteHarvest:
    """Read one site. Raises if a list page fails; counts case pages that fail."""
    out = SiteHarvest()
    urls: List[str] = []
    for list_url in site.list_urls:
        page = client.get(list_url)  # raises FetchError / RobotsDisallowed
        for u in case_links(page.text, page.url, site.case_pattern, site.case_text):
            if u not in urls:
                urls.append(u)
    for url in urls:
        try:
            page = client.get(url)
        except (FetchError, RobotsDisallowed) as e:
            out.failed_pages.append(f"{url} ({e})")
            continue
        out.case_pages += 1
        cp = parse_case_page(page.text, page.url, site.doc_pattern, site.debtor_xpath, site.debtor_from_title)
        if not cp.numero_processo:
            out.without_number.append(page.url)
            continue
        out.cases.append({
            "numero_processo": cp.numero_processo,
            "source": site.source,
            "vara": cp.vara,
            "devedor_nome": cp.devedor_nome,
            "aj_name": site.aj_name,
            "aj_case_url": page.url,
            "last_seen_at": seen_at,
        })
        for d in cp.documents:
            out.documents.append({
                "numero_processo": cp.numero_processo,
                "url": d.url,
                "tipo": classify_tipo(d.titulo, d.section),
                "titulo": d.titulo or None,
                "source": site.source,
                "found_on": page.url,
                "last_seen_at": seen_at,
            })
    return out


class RJIngestor:
    def __init__(self, pg: Any = None, client_factory=PoliteClient) -> None:
        self._pg = pg or get_pg_client()
        self._client_factory = client_factory
        self._head_budget = _env_int("RJ_HEAD_BUDGET", 300)

    def _stored_cases(self, source: str) -> int:
        with self._pg.cursor() as cur:
            cur.execute("SELECT count(*) FROM rj_case WHERE source = %s", (source,))
            return int(cur.fetchone()[0])

    def _unchecked_documents(self, source: str, limit: int) -> List[tuple]:
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT numero_processo, url FROM rj_document "
                "WHERE source = %s AND http_status IS NULL ORDER BY random() LIMIT %s",
                (source, limit),
            )
            return list(cur.fetchall())

    def _check_documents(self, client: PoliteClient, source: str) -> int:
        """HEAD up to the budget of this site's links never checked. Returns links checked.

        Random order: a link that cannot be checked (robots, network) stays
        NULL, and must not hold the head of the queue on every run.
        """
        checked = [(client.status(url), numero, url)
                   for numero, url in self._unchecked_documents(source, self._head_budget)]
        answered = [c for c in checked if c[0] is not None]
        if answered:
            # An UPDATE of existing rows, not an upsert: an INSERT carrying only
            # these columns would fail NOT NULL before ON CONFLICT is considered.
            with self._pg.cursor() as cur:
                cur.executemany(
                    "UPDATE rj_document SET http_status = %s WHERE numero_processo = %s AND url = %s",
                    answered)
        return len(answered)

    def _collect_sync(self, site: Site, seen_at: datetime) -> Outcome:
        client = self._client_factory()
        try:
            had = self._stored_cases(site.source)
            h = harvest_site(site, client, seen_at)
            if not h.cases and had:
                raise EmptySiteError(
                    f"{site.domain}: no case found ({h.case_pages} case pages read, "
                    f"{len(h.failed_pages)} failed) but {had} cases are stored")
            rows = upsert_rows(self._pg, "rj_case", h.cases, conflict_columns="numero_processo,source")
            rows += upsert_rows(self._pg, "rj_document", h.documents, conflict_columns="numero_processo,url")
            checked = self._check_documents(client, site.source)
        finally:
            client.close()
        note = (f"cases={len(h.cases)} documents={len(h.documents)} checked={checked} "
                f"no_number={len(h.without_number)} failed={len(h.failed_pages)}")
        if h.failed_pages:
            return Outcome(rows, status="error", error=f"{note}; first failures: {'; '.join(h.failed_pages[:3])}")
        return Outcome(rows, error=note)

    async def collect(self, sites: Sequence[Site]) -> Dict[str, int]:
        seen_at = datetime.now(timezone.utc)
        gate = asyncio.Semaphore(CONCURRENT_SITES)
        results: Dict[str, int] = {}
        failures: List[str] = []

        async def one(site: Site) -> None:
            async with gate:
                try:
                    results[site.domain] = await audited(
                        self._pg, ENTITY, site.source,
                        lambda: asyncio.to_thread(self._collect_sync, site, seen_at))
                except Exception as e:  # recorded by audited(); re-raised after every site ran
                    failures.append(f"{site.domain}: {type(e).__name__}: {e}")

        await asyncio.gather(*(one(s) for s in sites))
        if failures:
            raise RuntimeError(f"{len(failures)} of {len(sites)} RJ sites failed: " + " | ".join(failures))
        return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Collect RJ document links from AJ websites (#845).")
    parser.add_argument("--site", action="append", help="domain from sites.SITES; repeatable")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sites = [s for s in SITES if not args.site or s.domain in args.site]
    unknown = set(args.site or ()) - {s.domain for s in sites}
    if unknown:
        parser.error(f"unknown site(s): {sorted(unknown)}")
    results = asyncio.run(RJIngestor().collect(sites))
    logger.info("RJ collect: %s", results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
