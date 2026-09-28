"""B3 "Pesquisa por pregão" daily files: the Price Report and the reference rates.

WHY THIS EXISTS
---------------
DI1 futures and B3's DI x pré curve are not in COTAHIST. B3 used to show them
on www2.bmf.com.br ("Ajustes do pregão", "Sistema Pregão", "Taxas
referenciais"); B3 retired those pages on 2025-12-10 (its own notice on the
"Ajustes do pregão" page) and on 2026-09-26 they answered with an empty body
or `SQL Server does not exist`. The daily files below are what is left, and
they are the better record anyway.

THE CONTRACT (measured 2026-09-26/27, no auth, no cookie, no User-Agent needed)
------------------------------------------------------------------------------
    GET https://www.b3.com.br/pesquisapregao/download?filelist=<NAME>

    PRyymmdd.zip   Price Report, BVBG.086.01. A zip holding PRyymmdd.zip,
                   which holds 1–4 XML versions of the day's report (18:37,
                   19:04, 19:22, 20:31 BRT on 2026-09-25; DI1 identical in
                   all four). ~12 MB zipped, ~135 MB per XML in 2026.
                   First non-empty session: 2018-01-02. Every 2008–2017 date
                   tried returned an empty zip.
    TSyymmdd.ex_   Reference rates ("TaxaSwap"). A zip holding a Windows
                   self-extracting executable, which is itself a zip holding
                   TaxaSwap.txt (72-character fixed-width rows). Present on
                   2008-01-02; older dates untested.

A date that is not a session, or not published yet, answers HTTP 200 with a
22-byte EMPTY zip (not a 404). That is `B3FileNotPublished`, logged
`skipped`. Anything else unusable raises `B3FileFetchError`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import zipfile
from datetime import date
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.b3.com.br/pesquisapregao/download"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_CREATED = re.compile(rb"<CreDtAndTm>([^<]+)</CreDtAndTm>")


class B3FileNotPublished(LookupError):
    """B3 answered with an empty archive: not a session, or not published yet."""


class B3FileFetchError(RuntimeError):
    """Download failed after retries, or the archive is not the documented shape."""


def price_report_name(session: date) -> str:
    return f"PR{session:%y%m%d}.zip"


def taxa_swap_name(session: date) -> str:
    return f"TS{session:%y%m%d}.ex_"


def _open_zip(payload: bytes, label: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise B3FileFetchError(f"{label}: not a zip archive ({len(payload)} bytes)") from exc


def _single_member(zf: zipfile.ZipFile, label: str) -> bytes:
    names = zf.namelist()
    if not names:
        raise B3FileNotPublished(f"{label}: B3 returned an empty archive")
    if len(names) != 1:
        raise B3FileFetchError(f"{label}: expected one member, got {names}")
    return zf.read(names[0])


def _version_xml(inner: zipfile.ZipFile, name: str, label: str) -> Tuple[zipfile.ZipFile, str]:
    """(archive, member) holding one version's XML. B3 sometimes zips a version
    once more inside the archive (measured: PR230719.zip holds two BVBG...zip
    versions beside one BVBG...xml); such a zip must hold exactly one file."""
    if not name.lower().endswith(".zip"):
        return inner, name
    nested = _open_zip(inner.read(name), f"{label}: {name}")
    names = nested.namelist()
    if len(names) != 1:
        raise B3FileFetchError(f"{label}: {name} holds {names}, expected one XML")
    return nested, names[0]


def unwrap_price_report(payload: bytes, label: str) -> Tuple[str, bytes]:
    """(member name, XML bytes) of the LATEST version inside a PR archive.

    "Latest" is read from each version's own `CreDtAndTm` header, not from
    the file name; only the first 16 KB of each member is read to find it.
    """
    inner = _open_zip(_single_member(_open_zip(payload, label), label), label)
    versions = []
    for name in inner.namelist():
        archive, member = _version_xml(inner, name, label)
        with archive.open(member) as fh:
            head = fh.read(16_384)
        m = _CREATED.search(head)
        if not m:
            raise B3FileFetchError(f"{label}: {name} has no CreDtAndTm header")
        versions.append((m.group(1).decode(), member, archive))
    if not versions:
        raise B3FileNotPublished(f"{label}: inner archive is empty")
    _, latest, archive = max(versions, key=lambda v: (v[0], v[1]))
    return latest, archive.read(latest)


def unwrap_taxa_swap(payload: bytes, label: str) -> str:
    """TaxaSwap.txt as text. The self-extracting exe is a zip with a stub
    prepended, which `zipfile` reads directly (it locates the central
    directory from the end of the file)."""
    exe = _single_member(_open_zip(payload, label), label)
    inner = _open_zip(exe, label)
    if "TaxaSwap.txt" not in inner.namelist():
        raise B3FileFetchError(f"{label}: no TaxaSwap.txt in {inner.namelist()}")
    return inner.read("TaxaSwap.txt").decode("latin-1")


class B3PesquisaPregaoFetcher:
    """HTTP only. Parsing lives in src.parsers.b3_price_report / b3_taxa_swap."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        self.base_url = base_url or os.getenv("B3_PESQUISAPREGAO_URL") or DEFAULT_BASE_URL
        self.timeout = float(timeout if timeout is not None else os.getenv("B3_REQUEST_TIMEOUT", "300"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("B3_MAX_RETRIES", "3"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("B3_RETRY_DELAY", "2"))

    async def fetch_price_report(self, session: date) -> Tuple[str, bytes]:
        name = price_report_name(session)
        return unwrap_price_report(await self._download(name), name)

    async def fetch_taxa_swap(self, session: date) -> str:
        name = taxa_swap_name(session)
        return unwrap_taxa_swap(await self._download(name), name)

    async def _download(self, name: str) -> bytes:
        last_exc: Optional[BaseException] = None
        attempts = max(1, self.max_retries)
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), follow_redirects=True) as client:
            for attempt in range(1, attempts + 1):
                try:
                    resp = await client.get(self.base_url, params={"filelist": name})
                except httpx.HTTPError as exc:
                    last_exc = exc
                    logger.warning("B3 %s transport error attempt=%d/%d: %s", name, attempt, attempts, exc)
                    if attempt < attempts:
                        await asyncio.sleep(self.retry_delay * attempt)
                    continue
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = B3FileFetchError(f"{name}: HTTP {resp.status_code}")
                    logger.warning("B3 %s HTTP %s attempt=%d/%d", name, resp.status_code, attempt, attempts)
                    if attempt < attempts:
                        await asyncio.sleep(self.retry_delay * attempt)
                    continue
                if resp.status_code != 200:
                    raise B3FileFetchError(f"{name}: HTTP {resp.status_code}")
                if not resp.content:
                    raise B3FileFetchError(f"{name}: empty body")
                logger.info("B3 fetched %s (%d bytes)", name, len(resp.content))
                return resp.content
        raise B3FileFetchError(f"{name}: failed after {attempts} attempts: {last_exc}")
