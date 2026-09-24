"""B3 Fundos.NET (FNET) — the public register of fund documents, with versions.

What this is for: CVM's dados.cvm CSVs are republished in place, so a
restated informe overwrites the original and the fact that it was restated is
lost (CVM's FIDC files carry no version field at all). FNET keeps every
version as its own document, marks whether it is the original or a
restatement, and keeps superseded versions listed. This fetcher reads that
register — metadata only, no document bodies (docs/planning/COMPETITIVE_GAPS.md
§4.3, backlog B1).

Endpoint contract, verified live 2026-09-23/24:

    GET https://fnet.bmfbovespa.com.br/fnet/publico/pesquisarGerenciadorDocumentosDados
        ?d=1&s=<offset>&l=<page size ≤ 200>
        &dataInicial=dd/mm/yyyy&dataFinal=dd/mm/yyyy     (filters on delivery date)
        [&tipoFundo=1|2|3]   1 = FII, 2 = FIDC, 3 = ETF / index funds
        [&cnpjFundo=<14 digits>]
    Header: X-Requested-With: XMLHttpRequest     (no login, cookie or session)

  * The body is ``{draw, recordsTotal, recordsFiltered, data: [...]}``.
  * ``l`` above 200 fails; pages are walked with ``s``. The default order is
    NOT stable across pages (2026-08-02: 3 ids served twice, 3 never); the
    walk sorts by ``o[0][dataEntrega]=asc`` and repeats until the union of ids
    reaches ``recordsTotal``.
  * A MONTH-wide window times out (>120 s); a DAY answers in about a second.
    Windows are therefore one delivery day each.
  * Without a date window the endpoint returns an arbitrary 533 rows, so it
    is never called unwindowed except with ``cnpjFundo``, where it returns
    the fund's whole history (263 rows for FIDC PCG Brasil, recordsTotal 263).
  * ``cnpjFundo`` is null on EVERY row, even when the query filters on it.
    The CNPJ is known only because the caller asked for it; a document's fund
    is recorded as "FNET returned this id for cnpjFundo=X", never inferred
    from the fund name.
  * An unfiltered day (649 on 2026-09-01) is larger than tipoFundo 1+2+3
    (274+104+253 = 631): some documents belong to no queryable type. The
    register is built from the unfiltered crawl; the type is a label.
  * ``modalidade`` AP = Apresentação (original), RE = Reapresentação
    Espontânea, RC = Reapresentação por Exigência (CVM-required).
    ``status`` AC = active, IC = inactive (superseded), CC = cancelled; all
    remain listed and downloadable. Each version is a NEW ``id``; nothing
    links a version to its parent.

Integrity: a page count that does not reconcile with ``recordsTotal`` raises
(a silently short window is exactly how a register loses documents). Nothing
here fills or guesses; dates that do not parse stay NULL beside their raw text.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://fnet.bmfbovespa.com.br/fnet/publico"
PAGE_SIZE = 200
# Stable order matters: see ``search``. DataTables-style sort key.
_SORT_PARAM = "o[0][dataEntrega]"
_MAX_WALKS = 3

# tipoFundo query code → label. 4..6 return nothing (verified 2026-09-24).
FUND_TYPES: Dict[int, str] = {1: "FII", 2: "FIDC", 3: "ETF"}

_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": "SILO-BZ ingest (+https://github.com/PedroDnT/SILO-BZ)",
}
_RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504, 520, 522, 524})
_CNPJ_RE = re.compile(r"^\d{14}$")


class FnetFetchError(RuntimeError):
    """FNET did not answer usefully after the retries, or broke its contract."""


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class FnetFetcher:
    """HTTP only. Parsing is ``parse_documents`` below; storage is the pipeline."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        min_interval: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("FNET_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout if timeout is not None else os.getenv("FNET_REQUEST_TIMEOUT", "60"))
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("FNET_MAX_RETRIES", "5"))
        self.retry_delay = float(retry_delay if retry_delay is not None else os.getenv("FNET_RETRY_DELAY", "5"))
        # Politeness: FNET has no published terms and sits behind a firewall
        # that sets a cookie on every response. One request a second at most.
        self.min_interval = float(min_interval if min_interval is not None else os.getenv("FNET_MIN_INTERVAL", "1.0"))
        self._last_request = 0.0

    async def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _get_page(self, client: httpx.AsyncClient, params: Dict[str, Any], label: str) -> Dict[str, Any]:
        url = f"{self.base_url}/pesquisarGerenciadorDocumentosDados"
        attempts = max(1, self.max_retries)
        last_exc: Optional[BaseException] = None
        for attempt in range(1, attempts + 1):
            await self._pace()
            try:
                resp = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("FNET %s transport error attempt=%d/%d: %s", label, attempt, attempts, exc)
            else:
                if resp.status_code in _RETRY_STATUSES:
                    last_exc = FnetFetchError(f"{label} returned HTTP {resp.status_code}")
                    logger.warning("FNET %s HTTP %s attempt=%d/%d", label, resp.status_code, attempt, attempts)
                elif resp.status_code != 200:
                    raise FnetFetchError(f"{label} returned HTTP {resp.status_code}: {resp.text[:300]}")
                else:
                    try:
                        body = resp.json()
                    except ValueError as exc:
                        # An HTML challenge page served with 200: same remedy as a 403.
                        last_exc = FnetFetchError(f"{label} returned a non-JSON body: {resp.text[:120]!r}")
                        logger.warning("FNET %s non-JSON body attempt=%d/%d", label, attempt, attempts)
                    else:
                        if not isinstance(body, dict) or "data" not in body or "recordsTotal" not in body:
                            raise FnetFetchError(f"{label}: unexpected body keys {sorted(body)[:10] if isinstance(body, dict) else type(body)}")
                        return body
            if attempt < attempts:
                await asyncio.sleep(self.retry_delay * attempt)
        raise FnetFetchError(f"FNET {label} failed after {attempts} attempts: {last_exc!r}")

    async def search(
        self,
        *,
        day: Optional[date] = None,
        tipo_fundo: Optional[int] = None,
        cnpj: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Every document FNET lists for one delivery day and/or one fund.

        Walks every page and reconciles the count against ``recordsTotal``;
        a mismatch raises rather than return a short list.
        """
        if day is None and cnpj is None:
            raise ValueError("FNET search needs a delivery day or a cnpj: unwindowed queries return an arbitrary 533 rows")
        if tipo_fundo is not None and tipo_fundo not in FUND_TYPES:
            raise ValueError(f"tipo_fundo must be one of {sorted(FUND_TYPES)}, got {tipo_fundo}")
        if cnpj is not None and not _CNPJ_RE.match(cnpj):
            raise ValueError(f"cnpj must be 14 digits, got {cnpj!r}")

        base: Dict[str, Any] = {"d": 1, "l": PAGE_SIZE}
        if day is not None:
            base["dataInicial"] = base["dataFinal"] = _fmt(day)
        if tipo_fundo is not None:
            base["tipoFundo"] = tipo_fundo
        if cnpj is not None:
            base["cnpjFundo"] = cnpj
        label = " ".join(f"{k}={v}" for k, v in base.items() if k not in ("d", "l"))

        # FNET's default order is not stable between pages: on 2026-08-02 an
        # unsorted walk returned 3 ids twice and so skipped 3 others. Sorting
        # by delivery time fixes it on every day measured, but ties within a
        # minute can still reorder, so the walk is repeated (keeping the union
        # of ids) until the union holds exactly recordsTotal documents.
        base[_SORT_PARAM] = "asc"
        by_id: Dict[int, Dict[str, Any]] = {}
        total: Optional[int] = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), headers=_HEADERS,
                                     follow_redirects=True) as client:
            for walk in range(1, _MAX_WALKS + 1):
                offset = 0
                while True:
                    body = await self._get_page(client, {**base, "s": offset}, label)
                    page_total = int(body["recordsTotal"])
                    if total is None:
                        total = page_total
                    elif page_total != total:
                        raise FnetFetchError(f"FNET {label}: recordsTotal moved {total} -> {page_total} mid-walk")
                    page = body["data"] or []
                    for r in page:
                        if r.get("id") is not None:
                            by_id[r["id"]] = r
                    offset += len(page)
                    if not page or offset >= total:
                        break
                if len(by_id) >= (total or 0):
                    break
                logger.warning("FNET %s: walk %d/%d held %d of %d ids (unstable paging); walking again",
                               label, walk, _MAX_WALKS, len(by_id), total)
        if len(by_id) != total:
            raise FnetFetchError(
                f"FNET {label}: {len(by_id)} distinct ids after {_MAX_WALKS} walks but recordsTotal={total}")
        rows = list(by_id.values())
        logger.info("FNET %s: %d documents", label, len(rows))
        return rows


# ---------------------------------------------------------------------------
# Parsing — one FNET row → one fnet_document row. Pure; no I/O.
# ---------------------------------------------------------------------------

def _clean(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_delivery(raw: Optional[str]) -> Optional[datetime]:
    """'01/09/2026 01:57' → naive datetime in São Paulo local time, as FNET prints it."""
    if not raw:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_reference(raw: Optional[str]) -> Optional[date]:
    """dd/mm/yyyy → that day; mm/yyyy → first of the month (the repo's
    competência convention). A bare year, or anything else, stays NULL: the
    raw text is kept beside it and nothing is guessed."""
    if not raw:
        return None
    s = raw.strip()
    try:
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
            return datetime.strptime(s, "%d/%m/%Y").date()
        if re.fullmatch(r"\d{2}/\d{4}", s):
            return datetime.strptime("01/" + s, "%d/%m/%Y").date()
    except ValueError:
        return None
    return None


def parse_documents(raw_rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """FNET rows → (fnet_document rows, dropped count).

    A row is dropped (and counted) only when it lacks what the key and the
    register need: a positive integer ``id``, an integer ``versao`` ≥ 1, and a
    parseable delivery timestamp. Everything else is stored as published.
    """
    out: List[Dict[str, Any]] = []
    dropped = 0
    for r in raw_rows:
        try:
            fnet_id = int(r.get("id"))
            versao = int(r.get("versao"))
        except (TypeError, ValueError):
            dropped += 1
            continue
        delivered = _parse_delivery(_clean(r.get("dataEntrega")))
        if fnet_id <= 0 or versao < 1 or delivered is None:
            dropped += 1
            continue
        ref_raw = _clean(r.get("dataReferencia"))
        out.append({
            "fnet_id": fnet_id,
            "fund_name": _clean(r.get("descricaoFundo")),
            "fundo_ou_classe": _clean(r.get("fundoOuClasse")),
            "categoria": _clean(r.get("categoriaDocumento")),
            "tipo_documento": _clean(r.get("tipoDocumento")),
            "especie": _clean(r.get("especieDocumento")),
            "reference_raw": ref_raw,
            "reference_format": _clean(r.get("formatoDataReferencia")),
            "reference_date": _parse_reference(ref_raw),
            "delivered_at": delivered,
            "versao": versao,
            "modalidade": _clean(r.get("modalidade")),
            "status": _clean(r.get("status")),
            "situacao": _clean(r.get("situacaoDocumento")),
            "alta_prioridade": bool(r.get("altaPrioridade")) if r.get("altaPrioridade") is not None else None,
            "raw": r,
        })
    return out, dropped
