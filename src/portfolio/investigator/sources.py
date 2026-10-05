"""Where the investigator reads official documents: Fundos.NET, CVM RAD, and Exa as the fallback (#605).

Everything here is HTTP through one injected ``Http`` (``UrllibHttp`` in production: the engine image has
no httpx and does not ship ``src/fetchers/``; tests pass a recording fake). Every request carries only
public identifiers: an ISIN or CETIP code, a fund's or issuer's CNPJ, an FNET id, a public URL, and names
CVM publishes. Never the holder, the account, a quantity or a value from the statement.

**Fundos.NET** (``https://fnet.bmfbovespa.com.br/fnet/publico``), the contract of
``src/fetchers/fnet_fetcher.py`` plus the certificados page (#604 addendum, checked 2026-10-05):

* ``listarFundos?term=<ISIN>&idTipoFundo=6|5&paraCerts=true`` answers ``{"results": [{"id", "text"}]}``,
  the text naming securitizadora, CRA or CRI, issue, series, debtor and ISIN. It matches the ISIN; a CETIP
  code returned ``{"results": []}`` (2026-10-05), so a CRA or CRI reaches Fundos.NET only through its ISIN.
* ``pesquisarGerenciadorDocumentosDados?...&idFundo=<id>&paginaCertificados=true`` lists that
  certificate's documents (17 for the public example of #604, ``recordsTotal`` 17). Without
  ``paginaCertificados=true`` a CRA or CRI window returns 0 rows.
* ``...&cnpjFundo=<14 digits>`` lists a fund's whole history (no window needed).
* ``downloadDocumento?id=<fnet_id>``: the body, no login, no captcha.

**RAD**: SILO already indexes the debenture escrituras (``api.company_events``, category "Escrituras e
aditamentos de debêntures"), each with its RAD link; the investigator asks SILO, then GETs the link.

**Exa** (fallback, owner's choice over Firecrawl): ``POST https://api.exa.ai/agent/runs`` with ``query``,
``systemPrompt``, ``effort`` and ``outputSchema``; poll ``GET /agent/runs/{id}`` until ``completed``,
``failed`` or ``cancelled``; the facts are ``output.structured``. Then ``POST /contents`` with the cited
URL and ``text: true`` gives the page text the tiers are checked against. Key from ``EXA_API_KEY`` only,
sent as ``x-api-key`` and never logged (docs.exa.ai, read 2026-10-05).
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

FNET_BASE = "https://fnet.bmfbovespa.com.br/fnet/publico"
EXA_BASE = "https://api.exa.ai"
# tipoFundo on the certificados page (abrirGerenciadorDocumentosCertificadosCVM, #604): 6 CRA, 5 CRI.
CERT_TIPO = {"CRA": 6, "CRI": 5}
# Categories, in the order the owner asked for them: 17 and 19 first, then 16 and 36 (labels as served).
CAT_TERMO = "Termo de Securitização"
CAT_ADITAMENTO = "Aditamento de Termo de Securitização"
CAT_OFERTA = "Documentos de Oferta de Distribuição Pública"
CAT_RATING = "Relatório de agência classificadora de risco"
RAD_CATEGORY = "Escrituras e aditamentos de debêntures"
PAGE_SIZE = 200
_MAX_PAGES = 10
_ISIN = re.compile(r"^BR[A-Z0-9]{9}[0-9]$")
_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "User-Agent": "SILO-BZ investigator (+https://github.com/PedroDnT/SILO-BZ)",
}


class SourceError(RuntimeError):
    """A source did not answer usefully. ``code`` is fixed; the message never carries a response body."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


@dataclass
class HttpResponse:
    status: int
    content_type: str | None
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class Http(Protocol):
    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> HttpResponse: ...

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> HttpResponse: ...


class UrllibHttp:
    """Plain ``urllib`` with a timeout; no retry here (a failed read is reported, never filled)."""

    def __init__(self, timeout: float = 60.0, context: ssl.SSLContext | None = None):
        self.timeout = timeout
        self._ctx = context

    def _open(self, req: urllib.request.Request) -> HttpResponse:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as r:  # noqa: S310
                return HttpResponse(r.status, r.headers.get("content-type"), r.read())
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, e.headers.get("content-type") if e.headers else None, e.read() or b"")

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> HttpResponse:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        return self._open(urllib.request.Request(full, headers=headers or {}, method="GET"))

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> HttpResponse:
        body = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json", **(headers or {})}
        return self._open(urllib.request.Request(url, data=body, headers=h, method="POST"))


Charge = Callable[[str], None]  # called BEFORE each counted search; raises when the budget is spent


def _noop(_: str) -> None:
    return None


def is_isin(code: str | None) -> bool:
    return bool(_ISIN.match((code or "").strip().upper()))


class FnetReader:
    """Fundos.NET listings and downloads. Each listing page and each certificate lookup is one counted search."""

    def __init__(self, http: Http, base_url: str = FNET_BASE):
        self.http = http
        self.base = base_url.rstrip("/")

    def find_certificate(self, isin: str, tipo: str, charge: Charge = _noop) -> list[dict]:
        """The certificates whose label carries ``isin`` exactly (``listarFundos``, certificados page)."""
        if tipo not in CERT_TIPO:
            raise ValueError(f"tipo must be CRA or CRI, got {tipo!r}")
        isin = isin.strip().upper()
        charge("fnet_certificado")
        r = self.http.get(f"{self.base}/listarFundos",
                          {"term": isin, "page": 1, "idTipoFundo": CERT_TIPO[tipo], "idAdm": 0, "paraCerts": "true"},
                          _HEADERS)
        body = self._json(r, "fnet_listar_falhou")
        rows = body.get("results") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise SourceError("fnet_resposta_inesperada")
        return [x for x in rows if isinstance(x, dict) and isin in str(x.get("text") or "").upper().split()]

    def documents(self, *, id_fundo: int | None = None, tipo_fundo: int | None = None, cnpj: str | None = None,
                  certificados: bool = False, charge: Charge = _noop) -> list[dict]:
        """Every document FNET lists for one certificate (``id_fundo``) or one fund (``cnpj``), reconciled
        against ``recordsTotal``: a short list raises, it is never returned as complete."""
        if (id_fundo is None) == (cnpj is None):
            raise ValueError("pass exactly one of id_fundo or cnpj")
        params: dict[str, Any] = {"d": 1, "l": PAGE_SIZE, "o[0][dataEntrega]": "asc"}
        if id_fundo is not None:
            params["idFundo"] = int(id_fundo)
        if cnpj is not None:
            if not re.fullmatch(r"\d{14}", cnpj):
                raise ValueError("cnpj must be 14 digits")
            params["cnpjFundo"] = cnpj
        if tipo_fundo is not None:
            params["tipoFundo"] = int(tipo_fundo)
        if certificados:
            params["paginaCertificados"] = "true"
        by_id: dict[int, dict] = {}
        total: int | None = None
        offset = 0
        for _ in range(_MAX_PAGES):
            charge("fnet_listagem")
            body = self._json(self.http.get(f"{self.base}/pesquisarGerenciadorDocumentosDados",
                                            {**params, "s": offset}, _HEADERS), "fnet_listagem_falhou")
            if not isinstance(body, dict) or "data" not in body or "recordsTotal" not in body:
                raise SourceError("fnet_resposta_inesperada")
            total = int(body["recordsTotal"]) if total is None else total
            page = body.get("data") or []
            for row in page:
                if isinstance(row, dict) and row.get("id") is not None:
                    by_id[int(row["id"])] = row
            offset += len(page)
            if not page or offset >= total:
                break
        if total is None or len(by_id) != total:
            raise SourceError("fnet_listagem_incompleta", f"{len(by_id)} de {total}")
        return list(by_id.values())

    def download_url(self, fnet_id: int) -> str:
        return f"{self.base}/downloadDocumento?id={int(fnet_id)}"

    def download(self, fnet_id: int) -> HttpResponse:
        r = self.http.get(f"{self.base}/downloadDocumento", {"id": int(fnet_id)}, {"Accept": "*/*"})
        if r.status != 200 or not r.body or "html" in (r.content_type or "").lower():
            raise SourceError("documento_nao_baixado", f"HTTP {r.status}")
        return r

    @staticmethod
    def _json(r: HttpResponse, code: str) -> Any:
        if r.status != 200:
            raise SourceError(code, f"HTTP {r.status}")
        try:
            return r.json()
        except ValueError:
            raise SourceError(code, "corpo não JSON") from None


def fnet_delivered(row: dict) -> str:
    """``dataEntrega`` 'dd/mm/yyyy HH:MM' as a sortable 'yyyy-mm-dd HH:MM' (empty when absent)."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}:\d{2}))?", str(row.get("dataEntrega") or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {m.group(4) or '00:00'}" if m else ""


def fnet_reference(row: dict) -> str | None:
    """The document's date as FNET prints it (``dataReferencia``), never reparsed into another date."""
    v = str(row.get("dataReferencia") or "").strip()
    return v or None


class RadReader:
    """Debenture escrituras on CVM's RAD, found through SILO's own index (``api.company_events``)."""

    def __init__(self, http: Http):
        self.http = http

    def escrituras(self, client: Any, issuer_cnpj: str, charge: Charge = _noop) -> list[dict]:
        charge("rad_escrituras")
        return client.call("company_events", {"p_id": issuer_cnpj, "p_from": "2015-01-01",
                                              "p_category": RAD_CATEGORY})

    def download(self, url: str) -> HttpResponse:
        if not url.startswith("https://www.rad.cvm.gov.br/"):
            raise SourceError("link_rad_inesperado")
        r = self.http.get(url, None, {"Accept": "*/*", "User-Agent": _HEADERS["User-Agent"]})
        if r.status != 200 or not r.body:
            raise SourceError("documento_nao_baixado", f"HTTP {r.status}")
        return r


# Official domains, searched first (owner's resolution of #605, Q32). The issuer's, securitizadora's or
# manager's own site is also asked for in the query; the code labels a URL by its domain, never by the
# label the search gave it.
# ANBIMA Data is left out on purpose: its terms forbid automated collection (#604, section 1.1).
OFFICIAL_DOMAINS = ("cvm.gov.br", "b3.com.br", "bmfbovespa.com.br", "debentures.com.br")


def source_type_of(url: str, phase: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host.endswith("cvm.gov.br"):
        return "web_cvm"
    if host.endswith("b3.com.br") or host.endswith("bmfbovespa.com.br"):
        return "web_b3"
    if host.endswith("debentures.com.br"):
        return "web_snd"
    return "web_site_oficial_declarado" if phase == "official" else "web_busca_aberta"


@dataclass
class ExaClient:
    """Exa Agent runs and page contents. ``api_key`` comes from ``EXA_API_KEY``; it is never logged or shown."""

    http: Http
    api_key: str
    effort: str = "low"
    poll_interval_s: float = 4.0
    max_wait_s: float = 120.0
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    base_url: str = EXA_BASE
    cost_usd: float = field(default=0.0)

    def __repr__(self) -> str:  # never show the key
        return f"ExaClient(effort={self.effort!r}, max_wait_s={self.max_wait_s})"

    def _h(self) -> dict:
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    def agent_run(self, query: str, system_prompt: str, output_schema: dict) -> dict:
        """One Exa Agent run to a terminal state; ``output.structured`` or raises ``SourceError``."""
        r = self.http.post_json(f"{self.base_url}/agent/runs",
                                {"query": query, "systemPrompt": system_prompt, "effort": self.effort,
                                 "outputSchema": output_schema}, self._h())
        if r.status not in (200, 201, 202):
            raise SourceError("exa_falhou", f"HTTP {r.status}")
        run = r.json()
        started = self.monotonic()
        while str(run.get("status")) not in ("completed", "failed", "cancelled"):
            if self.monotonic() - started > self.max_wait_s:
                raise SourceError("exa_tempo_esgotado")
            self.sleep(self.poll_interval_s)
            g = self.http.get(f"{self.base_url}/agent/runs/{urllib.parse.quote(str(run.get('id') or ''))}",
                              None, self._h())
            if g.status != 200:
                raise SourceError("exa_falhou", f"HTTP {g.status}")
            run = g.json()
        cost = (run.get("costDollars") or {}).get("total") if isinstance(run.get("costDollars"), dict) else None
        if isinstance(cost, (int, float)):
            self.cost_usd += float(cost)
        if run.get("status") != "completed":
            raise SourceError("exa_falhou", str(run.get("status")))
        structured = (run.get("output") or {}).get("structured")
        return structured if isinstance(structured, dict) else {}

    def contents(self, url: str) -> tuple[str, str | None]:
        """``(text, published date)`` of one public URL, as Exa extracted it."""
        r = self.http.post_json(f"{self.base_url}/contents", {"urls": [url], "text": True}, self._h())
        if r.status != 200:
            raise SourceError("exa_conteudo_falhou", f"HTTP {r.status}")
        results = (r.json() or {}).get("results") or []
        if not results or not isinstance(results[0], dict) or not results[0].get("text"):
            raise SourceError("exa_conteudo_vazio")
        return str(results[0]["text"]), results[0].get("publishedDate")
