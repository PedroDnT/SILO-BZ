"""Resolve DJEN cases on their AJ's own website (#846, the resolver's second step).

    python -m src.pipeline.resolve_rj            # up to RJ_RESOLVE_BUDGET cases (default 150)

A DJEN case whose acts name an inventoried administrador judicial (``rj_case.aj_name``,
set by ``aj_index``) but that has no row from that AJ's site is searched for on that
one domain, and nowhere else:

1. the site's own search, ``https://<domain>/?s=<CNJ number>`` (WordPress, most AJ
   sites), read politely through ``PoliteClient`` (robots.txt, 1 request a second);
2. up to ``MAX_CANDIDATES`` same-domain pages the result links to are fetched;
3. a page is accepted only when the first CNJ number it prints is the case's own.

An accepted page becomes an ``rj_case`` row with ``source = 'aj_site:<domain>'`` and
``aj_case_url`` = that page, and its document links become ``rj_document`` rows,
exactly as the AJ collector writes them (the site's adapter ``doc_pattern`` when it
has one, else PDF links on the same domain). A case that is not found stays
unresolved: nothing is written for it, and it is tried again on a later run.

One ``cvm_ingest_log`` row per run: entity ``rj``, doc_type ``resolver``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence
from urllib.parse import urlsplit

from lxml import etree, html as lxml_html

from src.fetchers.rj.aj_index import aj_by_name
from src.fetchers.rj.client import FetchError, PoliteClient, RobotsDisallowed
from src.fetchers.rj.parse import parse_case_page
from src.fetchers.rj.sites import SITES, Site
from src.pipeline.ingest_log import Outcome, audited
from src.pipeline.ingest_rj import SiteHarvest, _read_case
from src.store.pg_client import get_pg_client, upsert_rows

logger = logging.getLogger(__name__)

ENTITY = "rj"
DOC_TYPE = "resolver"
MAX_CANDIDATES = 3
GENERIC_DOC = r"\.pdf(?:$|[?#])"


def masked(numero: str) -> str:
    """NNNNNNN-DD.AAAA.J.TR.OOOO, the form AJ sites print."""
    n = numero
    return f"{n[:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:]}"


def _same_domain(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


# Where search results sit, best first: result titles, then whole results, then the main area.
_RESULT_XPATHS = (
    "//article//*[self::h1 or self::h2 or self::h3 or self::h4]//a[@href]",
    "//article//a[@href]",
    "//main//a[@href]",
    "//*[contains(@class, 'search')]//a[@href]",
)
# The site's chrome: menus, header and footer repeat on every page and are never results.
_CHROME_XPATH = ("//nav//a[@href] | //footer//a[@href] | //header[not(ancestor::article)]//a[@href]"
                 " | //*[contains(@class, 'menu')]//a[@href]")


def candidates(search_html: str, base_url: str, domain: str) -> List[str]:
    """Same-domain result links on a search page, best first, without the site's chrome.

    Measured 2026-10-13 on acfb.com.br: its whole content area has a "search" class,
    so page order put eleven menu links before the one result inside <article>.
    """
    tree = lxml_html.fromstring(search_html)
    tree.make_links_absolute(base_url)
    chrome = {a.get("href").split("#")[0] for a in tree.xpath(_CHROME_XPATH)}
    out: List[str] = []
    for xpath in _RESULT_XPATHS:
        for a in tree.xpath(xpath):
            url = a.get("href").split("#")[0]
            path = urlsplit(url).path
            if (_same_domain(url, domain) and url not in out and url not in chrome and path not in ("", "/")
                    and not re.search(r"[?&](s|p|page_id)=|/(page|tag|category|author|feed|search)/"
                                      r"|\.(pdf|jpe?g|png)$", url)):
                out.append(url)
    return out


def _site_for(domain: str) -> Site:
    """The site's adapter when it has one, else a generic one reading PDF links."""
    for s in SITES:
        if s.domain == domain:
            return s
    return Site(domain=domain, aj_name="", list_urls=(), case_pattern="", doc_pattern=GENERIC_DOC, platform="")


@dataclass
class Resolution:
    tried: int = 0
    resolved: List[str] = field(default_factory=list)
    harvest: SiteHarvest = field(default_factory=SiteHarvest)


def resolve_case(client: Any, numero: str, domain: str, aj_name: str, seen_at: datetime, out: Resolution) -> bool:
    """Search one domain for one case; True when a page printing the number was accepted."""
    site = _site_for(domain)
    try:
        page = client.get(f"https://{domain}/?s={masked(numero)}")
        found = candidates(page.text, page.url, domain)
    except (FetchError, RobotsDisallowed):
        return False
    except etree.ParserError:  # an empty body (behrmannratis.com, 2026-10-13): nothing found
        return False
    for url in found[:MAX_CANDIDATES]:
        try:
            case_page = client.get(url)
            cp = parse_case_page(case_page.text, case_page.url, site.doc_pattern)
        except (FetchError, RobotsDisallowed, etree.ParserError):
            continue
        if cp.numero_processo != numero or not _same_domain(case_page.url, domain):
            continue
        _read_case(out.harvest, replace(site, aj_name=aj_name), case_page.text, case_page.url, seen_at)
        out.resolved.append(numero)
        return True
    return False


class Resolver:
    def __init__(self, pg: Any = None, client_factory=PoliteClient) -> None:
        self._pg = pg or get_pg_client()
        self._client_factory = client_factory
        self._budget = max(int(os.environ.get("RJ_RESOLVE_BUDGET", "150") or 150), 0)

    def _pending(self) -> List[tuple]:
        """DJEN cases naming an inventoried AJ with no row from any AJ site yet, at random."""
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT c.numero_processo, c.aj_name FROM rj_case c "
                "WHERE c.source = 'djen' AND c.aj_name IS NOT NULL AND NOT EXISTS ("
                "  SELECT 1 FROM rj_case a WHERE a.numero_processo = c.numero_processo "
                "  AND a.source LIKE 'aj_site:%%') "
                "ORDER BY random() LIMIT %s", (self._budget,))
            return list(cur.fetchall())

    def _run_sync(self, seen_at: datetime) -> Outcome:
        out = Resolution()
        client = self._client_factory()
        try:
            for numero, aj_name in self._pending():
                aj = aj_by_name(aj_name)
                if not aj:
                    continue
                out.tried += 1
                resolve_case(client, numero, aj.domain, aj_name, seen_at, out)
        finally:
            client.close()
        rows = upsert_rows(self._pg, "rj_case", out.harvest.cases, conflict_columns="numero_processo,source")
        rows += upsert_rows(self._pg, "rj_document", out.harvest.documents, conflict_columns="numero_processo,url")
        return Outcome(rows, error=f"tried={out.tried} resolved={len(out.resolved)} "
                                   f"documents={len(out.harvest.documents)}")

    async def run(self) -> int:
        seen_at = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        return await audited(self._pg, ENTITY, DOC_TYPE, lambda: asyncio.to_thread(self._run_sync, seen_at),
                             period_year=now.year, period_month=now.month)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argparse.ArgumentParser(description="Resolve DJEN RJ cases on their AJ's website (#846).").parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    rows = asyncio.run(Resolver().run())
    logger.info("RJ resolver: %s rows", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
