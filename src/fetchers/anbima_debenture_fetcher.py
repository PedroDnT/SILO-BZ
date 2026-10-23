"""Headless-browser reads of ANBIMA's public debenture, CRI and CRA pages (#1006, #1014).

data.anbima.com.br is a Next.js site: plain HTTP returns an empty shell and its
JSON backend needs a token, so this drives Chromium with Playwright and reads
what the page renders. It never logs in, never asks for a token and never
touches the reCAPTCHA or the rules-acceptance link.

One call returns one ``PageCapture``: the page's visible text and every table,
header-first, so the parser finds columns by name, never by position. A page
that does not render raises ``AnbimaPageError``; nothing is filled in.

The browser is ``ANBIMA_CHROMIUM_PATH`` when set (a cloud sandbox with a
preinstalled Chromium), otherwise Playwright's own (``playwright install
chromium`` in CI).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://data.anbima.com.br/debentures"
CRI_CRA_BASE_URL = "https://data.anbima.com.br/certificado-de-recebiveis"
PAGES = ("caracteristicas", "agenda", "precos")
AGENDA_PAGE_SIZE = 100
LIST_PAGE_SIZE = 100
_SHOWN = re.compile(r"Exibindo\s+(\d+)\s*-\s*(\d+)\s+de\s+(\d+)\s+resultados")

# Every table on the page as {"headers": [...], "rows": [[...], ...]}.
_TABLES_JS = """() => [...document.querySelectorAll('table')].map(t => ({
  headers: [...t.querySelectorAll('thead th')].map(c => c.innerText.replace(/\\s+/g, ' ').trim()),
  rows: [...t.querySelectorAll('tbody tr')].map(r =>
    [...r.querySelectorAll('td')].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))
}))"""
_FILLED_JS = """() => !(document.querySelector('main') || document.body).innerText
  .split('\\n').some(l => l.trim() === '--')"""
# The 5-session table is the one whose header names the indicative rate.
_RATE_TABLE_JS = """() => [...document.querySelectorAll('table')].some(t =>
  t.innerText.includes('Taxa de') && t.querySelectorAll('tbody tr td').length > 0)"""


class AnbimaPageError(RuntimeError):
    """The page did not render what it should. Never read as an empty result."""


@dataclass
class PageCapture:
    codigo: str
    page: str
    url: str
    observed_at: datetime
    text: str
    tables: list = field(default_factory=list)
    total_rows: Optional[int] = None  # agenda: ANBIMA's own "de N resultados"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class AnbimaDebentureFetcher:
    """Async context manager: one browser, ``concurrency`` tabs at most."""

    def __init__(self, *, concurrency: int = 2, timeout_s: float = 45.0,
                 rate_wait_s: float = 10.0, max_retries: int = 2,
                 executable_path: Optional[str] = None, base_url: str = BASE_URL,
                 ready_selector: str = "text=CNPJ"):
        # A CRI/CRA characteristics page prints the CNPJs without the word
        # "CNPJ", so it waits for its issue block instead.
        self.base_url = base_url
        self.ready_selector = ready_selector
        self.timeout_ms = int(timeout_s * 1000)
        self.rate_wait_ms = int(rate_wait_s * 1000)
        self.max_retries = max_retries
        self.executable_path = executable_path or os.getenv("ANBIMA_CHROMIUM_PATH") or None
        self._sem = asyncio.Semaphore(concurrency)
        self._pw = self._browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright  # optional dependency
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True, executable_path=self.executable_path)
        return self

    async def __aexit__(self, *exc):
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    async def fetch(self, codigo: str, page: str) -> PageCapture:
        if page not in PAGES:
            raise ValueError(f"unknown ANBIMA debenture page {page!r}")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._sem:
                    return await self._fetch_once(codigo, page)
            except AnbimaPageError as exc:
                last = exc
                logger.warning("ANBIMA %s/%s attempt %d failed: %s", codigo, page, attempt + 1, exc)
                await asyncio.sleep(2 * (attempt + 1))
        raise AnbimaPageError(f"{codigo}/{page}: {last}") from last

    async def _fetch_once(self, codigo: str, page: str) -> PageCapture:
        tab = await self._browser.new_page()
        try:
            if page == "agenda":
                return await self._agenda(tab, codigo)
            url = f"{self.base_url}/{codigo}/{page}"
            await self._goto(tab, url)
            if page == "caracteristicas":
                await self._wait(tab, self.ready_selector, url)
                # The page fills in progressively: '--' marks a value still
                # loading (a published blank is '-'). Never read it half-done.
                try:
                    await tab.wait_for_function(_FILLED_JS, timeout=self.timeout_ms)
                except Exception as exc:  # noqa: BLE001 — re-raised as a page failure
                    raise AnbimaPageError(f"{url}: values still loading ('--')") from exc
            else:
                # PU Histórico always renders; the rate table only for bonds that
                # have an indicative price. Its absence is recorded, not guessed.
                await self._wait(tab, "table tbody tr td", url)
                try:
                    await tab.wait_for_function(_RATE_TABLE_JS, timeout=self.rate_wait_ms)
                except Exception:  # noqa: BLE001 — absence is the observed state
                    logger.info("ANBIMA %s/precos: no indicative-rate table rendered", codigo)
            return PageCapture(codigo, page, url, datetime.now(timezone.utc),
                               await self._text(tab), await tab.evaluate(_TABLES_JS))
        finally:
            await tab.close()

    async def _agenda(self, tab, codigo: str) -> PageCapture:
        texts, rows, headers, total, n = [], [], None, None, 1
        first_url = f"{self.base_url}/{codigo}/agenda?page=1&size={AGENDA_PAGE_SIZE}"
        while True:
            url = f"{self.base_url}/{codigo}/agenda?page={n}&size={AGENDA_PAGE_SIZE}"
            await self._goto(tab, url)
            await self._wait(tab, "text=/Exibindo|Nenhum/", url)
            text = await self._text(tab)
            texts.append(text)
            tables = await tab.evaluate(_TABLES_JS)
            shown = _SHOWN.search(text)
            if shown is None:
                if not tables or not any(t["rows"] for t in tables):
                    total = 0  # a bond with no scheduled event says so; no counter
                    break
                raise AnbimaPageError(f"{url}: table rendered without its row counter")
            if not tables:
                raise AnbimaPageError(f"{url}: no agenda table")
            headers = headers or tables[0]["headers"]
            rows += tables[0]["rows"]
            total = int(shown.group(3))
            if int(shown.group(2)) >= total:
                break
            n += 1
        tables = [{"headers": headers or [], "rows": rows}] if headers else []
        return PageCapture(codigo, "agenda", first_url, datetime.now(timezone.utc),
                           "\n\f\n".join(texts), tables, total_rows=total)

    async def _goto(self, tab, url: str) -> None:
        try:
            await tab.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 — re-raised as a page failure
            raise AnbimaPageError(f"{url}: navigation failed: {exc}") from exc

    async def _wait(self, tab, selector: str, url: str) -> None:
        try:
            await tab.wait_for_selector(selector, timeout=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 — re-raised as a page failure
            body = (await self._text(tab))[:200]
            if "Erro no sistema" in body:
                raise AnbimaPageError(f"{url}: ANBIMA returned 'Erro no sistema'") from exc
            raise AnbimaPageError(f"{url}: {selector!r} never rendered") from exc

    @staticmethod
    async def _text(tab) -> str:
        main = await tab.query_selector("main")
        return await (main.inner_text() if main else tab.inner_text("body"))

    async def list_codes(self) -> list:
        """Every code on ANBIMA's search list for this asset, with whether it
        is priced today. Raises unless the pages hold exactly the total that
        ANBIMA states, so a partial list is never read as the universe."""
        from src.parsers.anbima_listing import parse_listing

        kind = self.base_url.rstrip("/").rsplit("/", 1)[1]
        seen: dict = {}
        n, total, expect = 0, None, 1  # the search list counts pages from 0
        tab = await self._browser.new_page()
        try:
            while True:
                # Sorted by the unique code: the default CRI/CRA sort (issue
                # date) has ties, so its pages repeat and skip codes.
                url = (f"{self.base_url.rsplit('/', 1)[0]}/busca/{kind}?page={n}&size={LIST_PAGE_SIZE}"
                       "&field=codigo_b3&order=asc")
                await self._goto(tab, url)
                await self._wait(tab, "text=/Exibindo/", url)
                listing = parse_listing(await self._text(tab))
                if listing.first != expect:
                    raise AnbimaPageError(f"{url}: shows {listing.first}-{listing.last}, expected {expect} first")
                expect = listing.last + 1
                if total is not None and listing.total != total:
                    raise AnbimaPageError(f"{url}: total changed from {total} to {listing.total} mid-list")
                total = listing.total
                for item in listing.items:
                    seen[item.codigo] = item
                if listing.last >= total:
                    break
                n += 1
        finally:
            await tab.close()
        if len(seen) != total:
            raise AnbimaPageError(f"{kind} list: {len(seen)} distinct codes, ANBIMA states {total}")
        return list(seen.values())
