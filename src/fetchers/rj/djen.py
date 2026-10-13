"""DJEN (CNJ's Diário de Justiça Eletrônico Nacional) as the RJ discovery source (#846).

DJEN answers HTTP 403 outside Brazil (#843: a GitHub runner and a cloud session
were both refused; an egress in São Paulo got HTTP 200). Every request here goes
out from Brazil, by one of two routes:

* ``DJEN_RELAY_URL`` + ``DJEN_RELAY_TOKEN``: our Edge Function
  ``supabase/functions/djen-relay``, invoked in ``sa-east-1`` (preferred);
* ``BR_PROXY_URL``: a Brazilian HTTP proxy.

With neither set the client refuses to start, so a run can never look like an
empty day.

The consult API (``GET /api/v1/comunicacao``, documented by third parties, its
shape measured on 2026-10-13) returns at most 100 items a page and reports a
``count`` capped at 10,000. A day for one tribunal stays well under that (a
whole month of TJSC text matches was 4,883); a day that reaches the cap raises,
because paging past it would silently miss items.

Items are kept only for the recuperação classes of the TPU: 129 (Recuperação
Judicial) and 128 (Recuperação Extrajudicial). A text search returns mostly
other processes that only mention a recovery (#843 sample: 1 to 6 % of items).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import httpx

BASE = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
USER_AGENT = "SILO-BZ RJ collector (+https://github.com/PedroDnT/SILO-BZ)"
PAGE_SIZE = 100
COUNT_CAP = 10_000
MIN_INTERVAL_S = 1.0
RELAY_REGION = "sa-east-1"
RJ_CLASSES = {"129", "128"}
SEARCH_TEXT = "recuperação judicial"

# siglaTribunal of the 27 state courts as DJEN spells them.
STATE_COURTS = (
    "TJAC", "TJAL", "TJAM", "TJAP", "TJBA", "TJCE", "TJDFT", "TJES", "TJGO",
    "TJMA", "TJMG", "TJMS", "TJMT", "TJPA", "TJPB", "TJPE", "TJPI", "TJPR",
    "TJRJ", "TJRN", "TJRO", "TJRR", "TJRS", "TJSC", "TJSE", "TJSP", "TJTO",
)


class DjenError(RuntimeError):
    """DJEN did not answer a page with HTTP 200 and JSON, or a day hit the count cap."""


@dataclass
class DjenItem:
    """The fields SILO keeps from one communication, as DJEN publishes them."""

    numero_processo: str        # 20 digits
    tribunal: str               # siglaTribunal
    orgao: Optional[str]        # nomeOrgao: the court division
    classe: Optional[str]       # nomeClasse
    codigo_classe: str
    tipo_comunicacao: Optional[str]
    tipo_documento: Optional[str]
    data_disponibilizacao: Optional[str]
    link: Optional[str]         # the act itself
    hash: Optional[str]         # its certidão: /comunicacao/{hash}/certidao
    texto: str                  # read for rules; never stored
    polo_ativo: List[str]       # destinatarios with polo "A": the recuperanda(s), as printed


def parse_item(raw: Dict[str, Any]) -> Optional[DjenItem]:
    """A DjenItem for an RJ-class item with a 20-digit process number; None otherwise."""
    code = str(raw.get("codigoClasse") or "")
    numero = "".join(c for c in str(raw.get("numero_processo") or "") if c.isdigit())
    if code not in RJ_CLASSES or len(numero) != 20:
        return None
    dest = raw.get("destinatarios") or []
    ativo = [str(d.get("nome")).strip() for d in dest
             if isinstance(d, dict) and d.get("polo") == "A" and d.get("nome")]
    return DjenItem(
        numero_processo=numero,
        tribunal=str(raw.get("siglaTribunal") or ""),
        orgao=raw.get("nomeOrgao"),
        classe=raw.get("nomeClasse"),
        codigo_classe=code,
        tipo_comunicacao=raw.get("tipoComunicacao"),
        tipo_documento=raw.get("tipoDocumento"),
        data_disponibilizacao=raw.get("data_disponibilizacao"),
        link=raw.get("link") or None,
        hash=raw.get("hash") or None,
        texto=str(raw.get("texto") or ""),
        polo_ativo=ativo,
    )


def certidao_url(item_hash: str) -> str:
    return f"{BASE}/{item_hash}/certidao"


class DjenClient:
    def __init__(self, proxy: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None,
                 sleep: Callable[[float], None] = time.sleep, relay_url: Optional[str] = None,
                 relay_token: Optional[str] = None) -> None:
        relay_url = (relay_url if relay_url is not None else os.environ.get("DJEN_RELAY_URL", "")).strip()
        relay_token = (relay_token if relay_token is not None else os.environ.get("DJEN_RELAY_TOKEN", "")).strip()
        proxy = proxy if proxy is not None else os.environ.get("BR_PROXY_URL", "").strip()
        use_relay = bool(relay_url and relay_token)
        if not (use_relay or proxy) and transport is None:
            raise DjenError("no Brazilian route: set DJEN_RELAY_URL with DJEN_RELAY_TOKEN, or BR_PROXY_URL "
                            "(DJEN refuses non-Brazilian egress, #843)")
        self._base, self._relay_headers = BASE, {}
        if use_relay:  # the relay runs in São Paulo; the act links are fetched directly
            self._base, proxy = relay_url, ""
            self._relay_headers = {"x-relay-token": relay_token, "x-region": RELAY_REGION}
        self._http = httpx.Client(proxy=proxy or None, transport=transport, timeout=60,
                                  headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._sleep = sleep
        self._last = 0.0

    def close(self) -> None:
        self._http.close()

    def _page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self._http.get(self._base, params=params, headers=self._relay_headers)
        except httpx.HTTPError as e:
            raise DjenError(f"DJEN unreachable: {type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise DjenError(f"DJEN HTTP {resp.status_code} for {params.get('siglaTribunal')} "
                            f"{params.get('dataDisponibilizacaoInicio')} page {params.get('pagina')}")
        try:
            payload = resp.json()
        except ValueError as e:
            raise DjenError("DJEN answered 200 but not JSON") from e
        if not isinstance(payload.get("items"), list):
            raise DjenError(f"DJEN reply has no items list; keys: {sorted(payload)}")
        return payload

    def status(self, url: str) -> Optional[int]:
        """HTTP status of a HEAD on a DJEN act link (GET when HEAD is refused); None on a network error."""
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self._http.head(url, follow_redirects=True)
            if resp.status_code in (403, 405, 501):
                with self._http.stream("GET", url, follow_redirects=True) as r:
                    return r.status_code
            return resp.status_code
        except httpx.HTTPError:
            return None

    def day(self, tribunal: str, day: date) -> List[DjenItem]:
        """Every RJ-class item one tribunal published on one day."""
        out: List[DjenItem] = []
        page = 1
        while True:
            payload = self._page({
                "siglaTribunal": tribunal,
                "dataDisponibilizacaoInicio": day.isoformat(),
                "dataDisponibilizacaoFim": day.isoformat(),
                "texto": SEARCH_TEXT,
                "pagina": page,
                "itensPorPagina": PAGE_SIZE,
            })
            if page == 1 and int(payload.get("count") or 0) >= COUNT_CAP:
                raise DjenError(f"{tribunal} {day}: count reached the {COUNT_CAP} cap; the day cannot be read completely")
            items = payload["items"]
            out.extend(i for i in (parse_item(r) for r in items) if i is not None)
            if len(items) < PAGE_SIZE:
                return out
            page += 1
