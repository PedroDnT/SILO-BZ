"""The investigator of official documents: triggers, budget, sources in order, facts with citations (#605).

Engine 1.12. Runs after every other block, only when the engine is given an ``Investigator`` (the server
builds one when ``SILO_INVESTIGATOR=on``; the CLI and the tests pass none, or one with fakes).

Triggers (owner's resolution of #605, Q33): a CRA, CRI or debenture line that is not identified, or whose
maturity diverges from the CVM registry; every FIP; every fund the movement block marks ``forte``.

Order of sources per trigger: Fundos.NET (certificados for a CRA or CRI, by its ISIN; the fund's own list
for a FIP or a fund), RAD for a debenture whose issuer CNPJ SILO knows, then Exa: official domains first,
then the open web. Exa is asked only when Fundos.NET and RAD gave no accepted fact.

Budget: at most 5 searches per trigger and 20 per report. A counted search is one FNET certificate
lookup, one FNET listing page, one ``company_events`` call or one Exa Agent run. A document download and
an Exa ``/contents`` read are reads, not searches. When the budget is spent the trigger says so.

Every fact passes ``tiers.assess`` (A, B or C) and is cross-checked against ``api.portfolio_instruments``
(the line's ``credit_match``): a divergence is shown beside the fact, never written over either value.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.portfolio.investigator import coordinators
from src.portfolio.investigator import extract as ex
from src.portfolio.report import llm
from src.portfolio.investigator.cache import DocumentCache
from src.portfolio.investigator.sources import (
    CAT_ADITAMENTO,
    CAT_OFERTA,
    CAT_RATING,
    CAT_TERMO,
    CERT_TIPO,
    OFFICIAL_DOMAINS,
    ExaClient,
    FnetReader,
    Http,
    RadReader,
    SourceError,
    fnet_delivered,
    fnet_reference,
    is_isin,
    source_type_of,
)
from src.portfolio.investigator.text import DocumentTextError, document_text, normalize
from src.portfolio.investigator.tiers import DISCARD_TEXT, TIER_A, TIER_B, TIER_C, TIER_LABEL, assess

log = logging.getLogger(__name__)

PER_TRIGGER = 5
PER_REPORT = 20
MAX_DOCS_PER_TRIGGER = 3
DEADLINE_S = 180.0  # one report waits for it inside one HTTP request

SOURCE_LABEL = {
    "fnet": "Fundos.NET",
    "rad": "RAD (CVM)",
    "web_cvm": "site oficial: CVM",
    "web_coordenador": "site do coordenador líder da oferta (lista revisada pelo dono)",
    "web_b3": "site oficial: B3",
    "web_snd": "site oficial: SND (debentures.com.br)",
    "web_dominio_nao_verificado": "site fora da lista oficial, achado na busca por fontes oficiais (domínio não verificado)",
    "web_busca_aberta": "busca aberta na web",
}
TRIED_LABEL = {"fnet": "Fundos.NET", "rad": "RAD", "official": "sites oficiais", "open": "busca aberta"}
KIND_LABEL = {
    "credito_nao_identificado": "crédito direto não identificado",
    "credito_vencimento_diverge": "crédito direto com vencimento divergente",
    "fip": "FIP",
    "movimento_forte": "movimento incomum forte",
    "consulta_manual": "consulta manual (scripts/investigate_documents.py)",
}
MSG_LIMIT_REPORT = f"limite de {PER_REPORT} buscas atingido; a conferir"
MSG_LIMIT_TRIGGER = f"limite de {PER_TRIGGER} buscas deste item atingido; a conferir"
MSG_DEADLINE = "tempo do investigador esgotado; a conferir"
MSG_LIMIT_COST = ("limite de custo do investigador atingido (US$" + f"{ex.INVESTIGATOR_SHARE_USD:.2f}".replace(".", ",") + " do teto de US$1,00 "
                  "do relatório); a conferir")
MSG_NO_EXA = "busca na web indisponível (EXA_API_KEY não configurada)"
_PREFIX = re.compile(r"^(CRA|CRI|DEB)-", re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                       "setembro", "outubro", "novembro", "dezembro"), start=1)}


class BudgetExhausted(Exception):
    def __init__(self, scope: str):
        self.scope = scope  # report | trigger | deadline | cost
        super().__init__(scope)


@dataclass
class Budget:
    per_trigger: int = PER_TRIGGER
    per_report: int = PER_REPORT
    deadline_s: float | None = DEADLINE_S
    monotonic: Callable[[], float] = time.monotonic
    used_report: int = 0
    cost_spent: bool = False
    used_trigger: int = 0
    by_kind: Counter = field(default_factory=Counter)
    _started: float | None = None

    def start(self) -> None:
        """A new report: the counters and the clock start again."""
        self._started = self.monotonic()
        self.used_report = self.used_trigger = 0
        self.by_kind = Counter()
        self.cost_spent = False

    def start_trigger(self) -> None:
        self.used_trigger = 0

    def check_time(self) -> None:
        """Raise when the wall clock is spent: checked before every search, download, extraction and judge call."""
        if self.deadline_s is not None and self._started is not None and self.monotonic() - self._started > self.deadline_s:
            raise BudgetExhausted("deadline")

    def charge(self, kind: str) -> None:
        self.check_time()
        if self.cost_spent:  # nothing read now could be extracted: stop searching
            raise BudgetExhausted("cost")
        if self.used_report >= self.per_report:
            raise BudgetExhausted("report")
        if self.used_trigger >= self.per_trigger:
            raise BudgetExhausted("trigger")
        self.used_report += 1
        self.used_trigger += 1
        self.by_kind[kind] += 1


@dataclass
class InvestigatorDeps:
    http: Http
    cache: DocumentCache
    models: ex.Models
    exa: ExaClient | None = None
    exa_note: str | None = None
    budget: Budget = field(default_factory=Budget)
    max_docs_per_trigger: int = MAX_DOCS_PER_TRIGGER
    coordinators_path: Any = coordinators.PATH


@dataclass
class _Trigger:
    trigger_id: str
    kind: str
    line_no: int
    tipo: str
    identifiers: dict[str, Any]  # public identifiers only: what may leave the engine
    credit: dict[str, Any] | None = None
    statement_vencimento: str | None = None
    fund_cnpj: str | None = None
    movement_month: str | None = None


@dataclass
class _Doc:
    document_id: str
    source: str  # fnet | rad | web
    source_type: str
    url: str
    title: str | None
    document_date: str | None
    fnet_id: int | None = None
    rad_protocol: str | None = None


def _iso_from_text(value: str) -> str | None:
    """A date written in the document ('15/02/2036', '15 de fevereiro de 2036') as ISO, for the cross-check only."""
    v = normalize(value)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", v)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})(?:º|o)? de ([a-z]+) de (\d{4})\b", v)
        if not m or m.group(2) not in _MONTHS:
            return None
        d, mo, y = int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def _digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


class Investigator:
    def __init__(self, deps: InvestigatorDeps, clock: Callable[[], dt.datetime] | None = None):
        self.deps = deps
        self.clock = clock

    # --- entry point -------------------------------------------------------------------------------

    def run(self, lines: list[Any], doc: dict[str, Any], client: Any, clock: Callable[[], dt.datetime]) -> dict[str, Any]:
        return self.run_triggers(find_triggers(lines, doc), client, clock)

    def run_triggers(self, triggers: list[_Trigger], client: Any, clock: Callable[[], dt.datetime]) -> dict[str, Any]:
        """The section for a given list of triggers (``run`` finds them; the by-hand script builds its own)."""
        now = (self.clock or clock)().astimezone(dt.timezone.utc)
        self._read_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._client = client
        self._fnet = FnetReader(self.deps.http)
        self._rad = RadReader(self.deps.http)
        self._facts: list[dict[str, Any]] = []
        self._docs: list[dict[str, Any]] = []
        self._doc_index: dict[str, dict[str, Any]] = {}
        self._discarded: Counter = Counter()
        self._coord_entries: list[Any] | None = None
        budget = self.deps.budget
        budget.start()
        out_triggers = []
        for t in triggers:
            budget.start_trigger()
            out_triggers.append(self._investigate(t))
        return self._section(out_triggers)

    # --- one trigger -------------------------------------------------------------------------------

    def _investigate(self, t: _Trigger) -> dict[str, Any]:
        tried: list[str] = []
        notes: list[str] = []
        stop: str | None = None
        first_fact = len(self._facts)
        self._trigger_first_fact = first_fact
        self._coord_domains: tuple[str, ...] = ()
        try:
            if t.kind in ("credito_nao_identificado", "credito_vencimento_diverge") or (
                    t.kind == "consulta_manual" and t.tipo in ("CRA", "CRI", "debênture")):
                self._credit_official(t, tried, notes)
            elif t.kind == "fip" or (t.kind == "consulta_manual" and t.tipo == "FIP"):
                self._fund_fnet(t, tried, notes, ex.FIP_FIELDS)
            elif t.kind == "movimento_forte":
                self._fund_fnet(t, tried, notes, ex.MOVEMENT_FIELDS)
            # the coordinator alone is not "something found": it only points the web search
            if not self._accepted_since(first_fact, exclude=("coordenador",)):
                self._web(t, tried, notes)
        except BudgetExhausted as b:
            stop = {"report": MSG_LIMIT_REPORT, "trigger": MSG_LIMIT_TRIGGER, "deadline": MSG_DEADLINE,
                    "cost": MSG_LIMIT_COST}[b.scope]
        except ex.CostShareSpent:
            self.deps.budget.cost_spent = True
            stop = MSG_LIMIT_COST
        except Exception as e:  # noqa: BLE001 - one item's failure is a note on that item; the others keep their facts
            log.warning("investigator item failed: %s", type(e).__name__)
            notes.append(f"falha inesperada nesta consulta ({getattr(e, 'code', None) or type(e).__name__})")
        facts = self._facts[first_fact:]
        n_a = sum(1 for f in facts if f["tier"] == TIER_A)
        n_b = sum(1 for f in facts if f["tier"] == TIER_B)
        if stop:
            message = stop
        elif n_a + n_b:
            message = f"{n_a + n_b} fato(s) com citação (nível A: {n_a}; nível B: {n_b})"
        else:
            where = ", ".join(TRIED_LABEL[s] for s in dict.fromkeys(tried)) or "nenhuma fonte aplicável"
            message = f"não encontrado em: {where}"
            if self.deps.exa is None:
                message += f"; {MSG_NO_EXA}"
        return {
            "trigger_id": t.trigger_id,
            "line_no": t.line_no,
            "kind": t.kind,
            "kind_label": KIND_LABEL[t.kind],
            "tipo": t.tipo,
            "identifiers": t.identifiers,
            "sources_tried": [TRIED_LABEL[s] for s in dict.fromkeys(tried)],
            "notes": notes,
            "searches_used": self.deps.budget.used_trigger,
            "limit_reached": stop is not None,
            "message": message,
            "fact_ids": [f["fact_id"] for f in facts],
            "coordinator": self._coordinator(t, first_fact),
        }

    def _accepted_since(self, first: int, exclude: tuple[str, ...] = ()) -> bool:
        return any(f["tier"] in (TIER_A, TIER_B) and f["field"] not in exclude for f in self._facts[first:])

    def _coordinator(self, t: _Trigger, first: int) -> dict[str, Any] | None:
        """The coordinator the issue's own documents name (an accepted fact), and the approved domains it maps to."""
        facts = [f for f in self._facts[first:] if f["field"] == "coordenador" and f["tier"] in (TIER_A, TIER_B)]
        if not facts:
            return None
        entries = self._coordinator_entries()
        domains = sorted({d for f in facts for d in coordinators.approved_domains(f["value"], entries)})
        status = ("aprovada" if domains else
                  "proposta, aguarda revisão do dono" if any(coordinators.proposed_match(f["value"], entries) for f in facts)
                  else "sem entrada na lista revisada")
        return {"value": facts[0]["value"], "fact_id": facts[0]["fact_id"], "domains": domains, "list_status": status}

    def _coordinator_entries(self) -> list[Any]:
        if self._coord_entries is None:
            try:
                self._coord_entries = coordinators.load(self.deps.coordinators_path)
            except Exception as e:  # noqa: BLE001 - a bad reviewed file disables the domains, never the report
                log.warning("coordinators.yaml unreadable: %s", type(e).__name__)
                self._coord_entries = []
        return self._coord_entries

    # --- credit: Fundos.NET certificados, then RAD -------------------------------------------------

    def _credit_official(self, t: _Trigger, tried: list[str], notes: list[str]) -> None:
        charge = self.deps.budget.charge
        if t.tipo in CERT_TIPO:
            tried.append("fnet")
            isin = t.identifiers.get("isin")
            if not isin:
                notes.append("Fundos.NET: sem ISIN; a lista de certificados encontra CRA e CRI só pelo ISIN")
                return
            try:
                certs = self._fnet.find_certificate(isin, t.tipo, charge)
                if len(certs) != 1:
                    notes.append(f"Fundos.NET: {len(certs)} certificado(s) com o ISIN; nada lido")
                    return
                rows = self._fnet.documents(id_fundo=int(certs[0]["id"]), tipo_fundo=CERT_TIPO[t.tipo],
                                            certificados=True, charge=charge)
            except SourceError as e:
                notes.append(f"Fundos.NET: {e.code}")
                return
            for row in _pick_certificate_docs(rows, self.deps.max_docs_per_trigger):
                self._read_fnet(t, row, ex.CREDIT_FIELDS)
            if not rows:
                notes.append("Fundos.NET: nenhum documento listado para o certificado")
        else:  # debênture
            tried.append("rad")
            issuer = t.identifiers.get("issuer_cnpj")
            if not issuer:
                notes.append("RAD: o SILO não tem o CNPJ do emissor desta debênture; RAD não consultado")
                return
            try:
                rows = self._rad.escrituras(self._client, issuer, charge)
            except BudgetExhausted:
                raise
            except Exception as e:  # noqa: BLE001 - a SILO refusal or failure is a note, never a guess
                notes.append(f"RAD: consulta ao SILO falhou ({type(e).__name__})")
                return
            rows = sorted(rows, key=lambda r: (str(r.get("delivery_date") or ""), str(r.get("protocol") or "")))
            cap = max(1, self.deps.max_docs_per_trigger)
            # the original escritura, then the newest aditamentos, never more than the cap
            picked = (rows[:1] + (rows[1:][-(cap - 1):] if cap > 1 else []))[:cap]
            for r in picked:
                self._read_rad(t, r)
            if not rows:
                notes.append("RAD: nenhuma escritura indexada para o emissor")

    # --- funds: Fundos.NET by CNPJ -----------------------------------------------------------------

    def _fund_fnet(self, t: _Trigger, tried: list[str], notes: list[str], fields: tuple[str, ...]) -> None:
        tried.append("fnet")
        if not t.fund_cnpj:
            notes.append("Fundos.NET: fundo sem CNPJ identificado; nada a consultar")
            return
        is_fip = fields == ex.FIP_FIELDS
        window = _movement_window(t.movement_month) if not is_fip else None
        if not is_fip and window is None:
            notes.append("Fundos.NET: mês do movimento ausente; nada a consultar")
            return
        try:
            # a FIP: the newest 200 deliveries in one search (its latest report is among them); a fund with a
            # forte month: the full list of the movement month and the two after it, reconciled
            rows = self._fnet.documents(cnpj=t.fund_cnpj, newest_page_only=is_fip, window=window,
                                        charge=self.deps.budget.charge)
        except SourceError as e:
            notes.append(f"Fundos.NET: {e.code}")
            return
        picked = _pick_fip_docs(rows) if is_fip else _pick_movement_docs(rows, t.movement_month)
        read_ok = 0
        for row in picked:
            if read_ok >= (1 if is_fip else self.deps.max_docs_per_trigger):
                break
            if self._read_fnet(t, row, fields):
                read_ok += 1
        if not picked:
            notes.append("Fundos.NET: nenhum documento do tipo procurado")

    # --- reading one document ----------------------------------------------------------------------

    def _read_fnet(self, t: _Trigger, row: dict, fields: tuple[str, ...]) -> bool:
        fid = int(row["id"])
        d = _Doc(document_id=f"fnet:{fid}", source="fnet", source_type="fnet", url=self._fnet.download_url(fid),
                 title=" / ".join(x for x in (row.get("categoriaDocumento"), row.get("tipoDocumento")) if x) or None,
                 document_date=fnet_reference(row), fnet_id=fid)
        return self._read(t, d, fields, lambda: self._fnet.download(fid))

    def _read_rad(self, t: _Trigger, r: dict) -> bool:
        proto = str(r.get("protocol") or "").strip() or None
        url = str(r.get("source_url") or "")
        d = _Doc(document_id=f"rad:{proto or hashlib.sha256(url.encode()).hexdigest()[:16]}", source="rad",
                 source_type="rad", url=url, title=" / ".join(str(x) for x in (r.get("category"), r.get("subject")) if x) or None,
                 document_date=str(r.get("reference_date") or r.get("delivery_date") or "")[:10] or None,
                 rad_protocol=proto)
        return self._read(t, d, ex.CREDIT_FIELDS, lambda: self._rad.download(url))

    def _text_of(self, d: _Doc, fetch: Callable[[], Any]) -> tuple[str, str]:
        cache = self.deps.cache
        cache_id = d.document_id.split(":", 1)[1]
        cached = cache.get(d.source, cache_id)
        if cached is not None:
            return cached.text, "hit"
        r = fetch()
        if isinstance(r, str):
            text = r
        else:
            text = document_text(r.body, r.content_type)
        cache.put(d.source, cache_id, text)
        return text, "miss"

    def _read(self, t: _Trigger, d: _Doc, fields: tuple[str, ...], fetch: Callable[[], Any]) -> bool:
        entry = self._doc_index.get(d.document_id)
        if entry is None:
            entry = {"document_id": d.document_id, "source_type": d.source_type,
                     "source_type_label": SOURCE_LABEL[d.source_type], "url": d.url, "title": d.title,
                     "document_date": d.document_date, "read_at_utc": self._read_at, "fnet_id": d.fnet_id,
                     "rad_protocol": d.rad_protocol, "status": None, "error_code": None, "cache": None,
                     "sha256": None, "n_chars": None, "trigger_ids": []}
            self._doc_index[d.document_id] = entry
            self._docs.append(entry)
        entry["trigger_ids"].append(t.trigger_id)
        self.deps.budget.check_time()
        try:
            text, hit = self._text_of(d, fetch)
        except (SourceError, DocumentTextError) as e:
            entry.update(status="não lido", error_code=getattr(e, "code", None) or "texto_ilegivel")
            return False
        except OSError as e:
            entry.update(status="não lido", error_code=f"rede_{type(e).__name__}")
            return False
        entry.update(status="lido", cache=hit, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     n_chars=len(text))
        self._extract_and_assess(t, d, text, fields)
        return True

    def _extract_and_assess(self, t: _Trigger, d: _Doc, text: str, fields: tuple[str, ...]) -> None:
        models = self.deps.models
        if models.extractor is None:
            return
        meta = {"source": SOURCE_LABEL[d.source_type], "title": d.title, "date": d.document_date}
        self.deps.budget.check_time()
        try:
            extracted = ex.extract(models.extractor, fields, t.identifiers, meta, text)
        except ex.CostShareSpent:
            raise
        except llm.CostCapExceeded:
            raise ex.CostShareSpent("report cap") from None
        except Exception as e:  # noqa: BLE001 - LLMError: the document is read, nothing extracted
            log.warning("investigator extractor failed: %s", type(e).__name__)
            self._doc_index[d.document_id]["error_code"] = f"extrator_{type(e).__name__}"
            return
        nt = normalize(text)
        judge = ex.judge_fn(models.judge) if models.tier_b_enabled and models.judge is not None else None
        for f in extracted:
            self.deps.budget.check_time()
            v = assess(f.field, f.value, f.quote, text, judge, nt)
            if v.tier == TIER_C:
                self._discarded[v.reason_code or "outro"] += 1
                continue
            self._add_fact(t, d, f.field, f.value, f.quote, f.subject, v)

    def _add_fact(self, t: _Trigger, d: _Doc, fld: str, value: str, quote: str, subject: str | None, v) -> None:
        self._facts.append({
            "fact_id": f"f{len(self._facts) + 1}",
            "trigger_id": t.trigger_id,
            "line_no": t.line_no,
            "field": fld,
            "field_label": ex.FIELD_LABEL[fld],
            "subject": subject,
            "value": value,
            "quote": quote,
            "passage": v.passage if v.tier == TIER_B else None,
            "passage_ratio": v.passage_ratio if v.tier == TIER_B else None,
            "url": d.url,
            "document_id": d.document_id,
            "document_title": d.title,
            "document_date": d.document_date,
            "read_at_utc": self._read_at,
            "read_date": self._read_at[:10],
            "source_type": d.source_type,
            "source_type_label": SOURCE_LABEL[d.source_type],
            "tier": v.tier,
            "tier_label": TIER_LABEL[v.tier],
            "fnet_id": d.fnet_id,
            "rad_protocol": d.rad_protocol,
            "cross_check": _cross_check(t, fld, value, subject),
        })

    # --- Exa: official domains first, then the open web --------------------------------------------

    def _web(self, t: _Trigger, tried: list[str], notes: list[str]) -> None:
        exa = self.deps.exa
        if exa is None:
            return
        if not any(t.identifiers.get(k) for k in ("codigo", "isin", "cnpj", "issuer_cnpj", "cnpj_securitizadora")):
            # a search with no public identifier would attach any fund's or issuer's document to this line
            notes.append("busca na web não feita: nenhum identificador público (código, ISIN ou CNPJ)")
            return
        fields = _fields_of(t)
        coord = self._coordinator(t, self._trigger_first_fact)
        self._coord_domains = tuple(coord["domains"]) if coord else ()
        for phase in ("official", "open"):
            tried.append(phase)
            self.deps.budget.charge("exa_agent")
            q, sp = exa_request(t, fields, phase, self._coord_domains)
            try:
                out = exa.agent_run(q, sp, exa_output_schema(fields))
            except SourceError as e:
                notes.append(f"Exa ({TRIED_LABEL[phase]}): {e.code}")
                continue
            first = len(self._facts)
            for raw in (out.get("facts") or [])[:12]:
                self._web_fact(t, raw, phase, fields)
            if self._accepted_since(first):
                return

    def _web_fact(self, t: _Trigger, raw: Any, phase: str, fields: tuple[str, ...]) -> None:
        if not isinstance(raw, dict):
            self._discarded["sem_valor_ou_citacao"] += 1
            return
        fld, url = str(raw.get("field") or ""), str(raw.get("url") or "")
        if fld not in fields:
            self._discarded["campo_desconhecido"] += 1
            return
        if not url.startswith("https://"):
            self._discarded["sem_valor_ou_citacao"] += 1
            return
        stype = source_type_of(url, phase, self._coord_domains)
        uid = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        d = _Doc(document_id=f"web:{uid}", source="web", source_type=stype, url=url,
                 title=str(raw.get("document_title") or "") or None,
                 document_date=str(raw.get("document_date") or "") or None)
        published: list[str | None] = []

        def fetch() -> str:
            text, pub = self.deps.exa.contents(url)  # type: ignore[union-attr]
            published.append(pub)
            return text

        self.deps.budget.check_time()
        if d.document_id in self._doc_index and t.trigger_id not in self._doc_index[d.document_id]["trigger_ids"]:
            self._doc_index[d.document_id]["trigger_ids"].append(t.trigger_id)
        if d.document_id not in self._doc_index or self._doc_index[d.document_id]["status"] != "lido":
            entry_ok = self._read_web(t, d, fetch)
            if not entry_ok:
                self._discarded["trecho_nao_localizado"] += 1
                return
        text = self.deps.cache.get("web", uid)
        if text is None:
            self._discarded["trecho_nao_localizado"] += 1
            return
        if not _page_names_the_asset(t, text.text):
            # a quote can be verbatim in a page about ANOTHER asset: the page must name this one
            self._discarded["documento_sem_identificador"] += 1
            return
        if d.document_date is None and published and published[0]:
            d.document_date = str(published[0])[:10]
        judge = ex.judge_fn(self.deps.models.judge) if self.deps.models.tier_b_enabled else None
        v = assess(fld, str(raw.get("value") or ""), str(raw.get("quote") or ""), text.text, judge)
        if v.tier == TIER_C:
            self._discarded[v.reason_code or "outro"] += 1
            return
        self._add_fact(t, d, fld, str(raw.get("value")), str(raw.get("quote")), raw.get("subject"), v)

    def _read_web(self, t: _Trigger, d: _Doc, fetch: Callable[[], str]) -> bool:
        entry = self._doc_index.get(d.document_id)
        if entry is None:
            entry = {"document_id": d.document_id, "source_type": d.source_type,
                     "source_type_label": SOURCE_LABEL[d.source_type], "url": d.url, "title": d.title,
                     "document_date": d.document_date, "read_at_utc": self._read_at, "fnet_id": None,
                     "rad_protocol": None, "status": None, "error_code": None, "cache": None, "sha256": None,
                     "n_chars": None, "trigger_ids": []}
            self._doc_index[d.document_id] = entry
            self._docs.append(entry)
        entry["trigger_ids"].append(t.trigger_id)
        try:
            text, hit = self._text_of(d, fetch)
        except (SourceError, OSError) as e:
            entry.update(status="não lido", error_code=getattr(e, "code", None) or f"rede_{type(e).__name__}")
            return False
        entry.update(status="lido", cache=hit, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     n_chars=len(text))
        return True

    # --- the section ---------------------------------------------------------------------------------

    def _section(self, triggers: list[dict[str, Any]]) -> dict[str, Any]:
        b = self.deps.budget
        n_disc = sum(self._discarded.values())
        codes: list[str] = []
        if not triggers:
            status, reason = "not_applicable", "Nenhum gatilho do investigador na carteira."
            codes.append("sem_gatilho_investigador")
        else:
            done = sum(1 for t in triggers if t["fact_ids"])
            status = "complete" if done == len(triggers) else "partial"
            reason = f"{done} de {len(triggers)} item(ns) com fato citado."
            if done < len(triggers):
                codes.append("investigacao_parcial")
            if any(t["limit_reached"] for t in triggers):
                codes.append("limite_buscas")
            if self.deps.exa is None:
                codes.append("busca_web_indisponivel")
            if not self.deps.models.tier_b_enabled:
                codes.append("nivel_b_desligado")
        facts = self._facts
        return {
            "status": status,
            "reason": reason,
            "reason_codes": codes,
            "errors": [],
            "enabled": True,
            "limits": {"searches_per_trigger": b.per_trigger, "searches_per_report": b.per_report,
                       "max_documents_per_trigger": self.deps.max_docs_per_trigger,
                       "counted": "consulta de certificado e página de listagem do Fundos.NET, consulta company_events "
                                  "(RAD) e execução do Exa Agent; download de documento e leitura de página não contam"},
            "searches_used": b.used_report,
            "searches_by_kind": dict(sorted(b.by_kind.items())),
            "costs": _costs(self.deps),
            "web_search": {"provider": "exa", "available": self.deps.exa is not None,
                           "note": self.deps.exa_note if self.deps.exa is None else None},
            "models": self.deps.models.as_dict(),
            "tiers": {k: TIER_LABEL[k] for k in (TIER_A, TIER_B, TIER_C)},
            "counts": {"triggers": len(triggers), "facts": len(facts),
                       "tier_a": sum(1 for f in facts if f["tier"] == TIER_A),
                       "tier_b": sum(1 for f in facts if f["tier"] == TIER_B),
                       "discarded": n_disc,
                       "divergences": sum(1 for f in facts if (f["cross_check"] or {}).get("agrees") is False),
                       "documents_read": sum(1 for d in self._docs if d["status"] == "lido"),
                       "documents_not_read": sum(1 for d in self._docs if d["status"] != "lido")},
            "triggers": triggers,
            "facts": facts,
            "discarded": {"count": n_disc, "text": f"{n_disc} fatos descartados",
                          "by_reason": {k: {"count": v, "text": DISCARD_TEXT.get(k, k)}
                                        for k, v in sorted(self._discarded.items())}},
            "documents_consulted": self._docs,
            "messages": [(f"linha {t['line_no']} ({t['kind_label']}): " if t["line_no"] else f"{t['tipo']} ({t['kind_label']}): ")
                         + t["message"] for t in triggers],
            "note": ("Fatos lidos em documentos oficiais públicos, cada um com a citação, o endereço e a data de leitura. "
                     "Nível A: citação encontrada no texto do documento. Nível B: conferido por um segundo modelo; a "
                     "conferir. Nenhum número vem de um modelo: todo número mostrado está no trecho do documento. "
                     "Divergência com o registro da CVM é mostrada, nunca corrigida."),
        }


# --- triggers --------------------------------------------------------------------------------------

def _fields_of(t: _Trigger) -> tuple[str, ...]:
    if t.kind == "movimento_forte":
        return ex.MOVEMENT_FIELDS
    if t.kind == "fip" or t.tipo == "FIP":
        return ex.FIP_FIELDS
    return ex.CREDIT_FIELDS


def manual_trigger(n: int, tipo: str, *, codigo: str | None = None, isin: str | None = None, cnpj: str | None = None,
                   nome_cvm: str | None = None, credit: dict[str, Any] | None = None,
                   statement_vencimento: str | None = None) -> _Trigger:
    """A trigger built by hand from PUBLIC identifiers only (the by-hand script; never a client's line)."""
    ids = {"tipo": tipo, "codigo": codigo, "isin": isin, "cnpj": cnpj, "nome_cvm": nome_cvm,
           "cnpj_securitizadora": (credit or {}).get("cnpj_securit")}
    return _Trigger(f"t{n}", "consulta_manual", 0, tipo, {k: v for k, v in ids.items() if v}, credit=credit,
                    statement_vencimento=statement_vencimento, fund_cnpj=cnpj if tipo == "FIP" else None)


def find_triggers(lines: list[Any], doc: dict[str, Any]) -> list[_Trigger]:
    """The lines the investigator reads documents for, in line order (credit, FIP, then movement)."""
    out: list[_Trigger] = []
    movement = doc.get("movement") or {}
    forte = set(movement.get("investigator_trigger_line_nos") or [])
    month = movement.get("month")
    for li in lines:
        p = li.position
        tipo = p.tipo
        if tipo in ("CRA", "CRI", "debênture"):
            credit = li.credit or {}
            flags = {f.get("code") for f in credit.get("flags") or []}
            kind = None
            if li.status != "identified":
                kind = "credito_nao_identificado"
            elif "vencimento_diverge" in flags:
                kind = "credito_vencimento_diverge"
            if kind:
                code = str(credit.get("code") or _PREFIX.sub("", str(p.codigo or "").strip())).strip().upper() or None
                # cd_isin is served as filed (catalog v67), so "00000" or "NÃO TEM" can arrive: only an ISIN-shaped
                # value is a Fundos.NET search term.
                served = credit.get("cd_isin")
                isin = served if is_isin(served) else (code if is_isin(code) else None)
                ids = {"tipo": tipo, "codigo": code, "isin": isin,
                       "cnpj_securitizadora": credit.get("cnpj_securit"),
                       "issuer_cnpj": li.issuer_cnpj, "issuer_code": li.issuer_code}
                out.append(_Trigger(f"t{len(out) + 1}", kind, li.line_no, tipo,
                                    {k: v for k, v in ids.items() if v}, credit=credit or None,
                                    statement_vencimento=p.vencimento.isoformat() if p.vencimento else None))
        if li.entity_type == "fip" or (tipo == "FIP" and li.status == "identified"):
            ids = {"tipo": "FIP", "cnpj": li.cnpj, "nome_cvm": li.name}
            out.append(_Trigger(f"t{len(out) + 1}", "fip", li.line_no, "FIP", {k: v for k, v in ids.items() if v},
                                fund_cnpj=li.cnpj))
        elif tipo == "FIP":
            out.append(_Trigger(f"t{len(out) + 1}", "fip", li.line_no, "FIP", {"tipo": "FIP"}))
        if li.line_no in forte:
            ids = {"tipo": tipo, "cnpj": li.cnpj, "nome_cvm": li.name}
            out.append(_Trigger(f"t{len(out) + 1}", "movimento_forte", li.line_no, tipo,
                                {k: v for k, v in ids.items() if v}, fund_cnpj=li.cnpj, movement_month=month))
    return out


def _cnpj_forms(c: str) -> tuple[str, ...]:
    d = _digits(c)
    if len(d) != 14:
        return ()
    return (d, f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}")


def _page_names_the_asset(t: _Trigger, text: str) -> bool:
    """The web page names THIS asset: its code or ISIN (a credit line; a debenture also by its issuer's CNPJ),
    or its CNPJ or CVM name (a fund). The securitizadora's CNPJ alone is not enough: it issues many CRAs."""
    ids = t.identifiers
    nt = normalize(text)
    names: list[str] = [ids.get("codigo") or "", ids.get("isin") or ""]
    if t.tipo == "debênture":
        names += list(_cnpj_forms(ids.get("issuer_cnpj") or ""))
    if t.tipo not in ("CRA", "CRI", "debênture"):
        names += list(_cnpj_forms(ids.get("cnpj") or "")) + [ids.get("nome_cvm") or ""]
    return any(len(n) >= 6 and normalize(n) in nt for n in names)


# --- choosing documents ----------------------------------------------------------------------------

def _active(rows: list[dict]) -> list[dict]:
    return [r for r in rows if str(r.get("status") or "AC").upper() != "CC"]


def _pick_certificate_docs(rows: list[dict], cap: int) -> list[dict]:
    """The original termo, then the newest aditamentos; when there are none, the offer and rating documents."""
    rows = sorted(_active(rows), key=fnet_delivered)
    termos = [r for r in rows if r.get("categoriaDocumento") == CAT_TERMO]
    adit = [r for r in rows if r.get("categoriaDocumento") == CAT_ADITAMENTO]
    first = (termos[:1] + adit[-(cap - 1):]) if termos else adit[-cap:]
    if first:
        return first[:cap]
    rest = [r for r in rows if r.get("categoriaDocumento") in (CAT_OFERTA, CAT_RATING)]
    return rest[-cap:]


# Structured monthly informes and the CDA carry no investee list; the rest of "Informes Periódicos" may.
_FIP_SKIP = ("informe mensal estruturado", "composicao da carteira")


def _pick_fip_docs(rows: list[dict]) -> list[dict]:
    """The FIP's periodic reports, newest delivery first (the first one that reads is used)."""
    per = [r for r in _active(rows) if normalize(r.get("categoriaDocumento")) == "informes periodicos"
           and not any(s in normalize(r.get("tipoDocumento")) for s in _FIP_SKIP)
           and str(r.get("status") or "AC").upper() == "AC"]
    return sorted(per, key=fnet_delivered, reverse=True)[:3]


def _movement_bounds(month: str | None) -> tuple[dt.date, dt.date] | None:
    """First day of the movement month and last day of the second month after it."""
    if not month:
        return None
    m0 = dt.date.fromisoformat(month[:10]).replace(day=1)
    end_month = m0.month + 2
    y, mo = m0.year + (end_month - 1) // 12, (end_month - 1) % 12 + 1
    return m0, dt.date(y, mo, calendar.monthrange(y, mo)[1])


def _movement_window(month: str | None) -> tuple[str, str] | None:
    b = _movement_bounds(month)
    return (b[0].strftime("%d/%m/%Y"), b[1].strftime("%d/%m/%Y")) if b else None


def _pick_movement_docs(rows: list[dict], month: str | None) -> list[dict]:
    """Fato relevante, comunicado or management report delivered in the movement month or the two after it."""
    b = _movement_bounds(month)
    if not b:
        return []
    m0, end_d = b
    end = end_d.isoformat()
    wanted = ("fato relevante", "comunicado ao mercado", "relatorio gerencial")
    out = []
    for r in _active(rows):
        day = fnet_delivered(r)[:10]
        label = normalize(f"{r.get('categoriaDocumento')} {r.get('tipoDocumento')}")
        if m0.isoformat() <= day <= end and any(w in label for w in wanted):
            out.append(r)
    return sorted(out, key=fnet_delivered, reverse=True)


# --- cross-check against portfolio_instruments -------------------------------------------------------

_ORDINALS = {"primeira": 1, "segunda": 2, "terceira": 3, "quarta": 4, "quinta": 5, "sexta": 6, "setima": 7,
             "oitava": 8, "nona": 9, "decima": 10}


def _series_of(subject: str | None) -> int | None:
    """The series a fact's subject names ('CRA da Terceira Série', '1ª série', 'série 2'), else None."""
    s = normalize(subject)
    if "serie" not in s:
        return None
    for word, n in _ORDINALS.items():
        if re.search(rf"\b{word}\s+serie", s):
            return n
    m = re.search(r"\b(\d{1,3})\s*(?:a|o)?\s+serie\b|\bserie\s+(\d{1,3})\b", s)
    return int(m.group(1) or m.group(2)) if m else None


def _cross_check(t: _Trigger, fld: str, value: str, subject: str | None = None) -> dict[str, Any] | None:
    """The fact beside SILO's registry value (``credit_match``). Agreement is judged only where it is exact
    (a date, a CNPJ) and about the same series; elsewhere both are shown and ``agrees`` is null. Neither value
    is ever changed."""
    c = t.credit or {}
    if not c.get("matched"):
        return None
    if fld == "vencimento":
        reg = c.get("data_vencimento")
        doc_iso = _iso_from_text(value)
        fact_series, reg_series = _series_of(subject), c.get("numero_serie")
        other = fact_series is not None and reg_series is not None and str(fact_series) != str(reg_series).strip()
        agrees = None if other else ((doc_iso == reg) if (doc_iso and reg) else None)
        note = (f"fato da série {fact_series}; o registro é da série {reg_series}: não comparado" if other
                else "diverge do registro da CVM; a conferir" if agrees is False else None)
        return {"silo_field": "portfolio_instruments.data_vencimento", "silo_value": reg, "silo_serie": reg_series,
                "document_value_iso": doc_iso, "statement_vencimento": t.statement_vencimento, "agrees": agrees,
                "note": note}
    if fld == "emissor_cnpj" and c.get("cnpj_securit"):
        d = _digits(value)
        agrees = (d == c["cnpj_securit"]) if len(d) == 14 else None
        return {"silo_field": "portfolio_instruments.cnpj_securit", "silo_value": c["cnpj_securit"], "agrees": agrees,
                "note": "diverge do registro da CVM; a conferir" if agrees is False else None}
    if fld == "indexador" and c.get("taxa_juros"):
        return {"silo_field": "portfolio_instruments.taxa_juros", "silo_value": c["taxa_juros"], "agrees": None,
                "note": "texto livre nas duas fontes: comparar a olho"}
    if fld == "rating":
        return {"silo_field": "portfolio_instruments.classificacao_risco_atual",
                "silo_value": c.get("classificacao_risco_atual"), "agrees": None,
                "note": "texto livre nas duas fontes: comparar a olho"}
    return None


# --- Exa request (public identifiers only) -----------------------------------------------------------

def exa_request(t: _Trigger, fields: tuple[str, ...], phase: str,
                coordinator_domains: tuple[str, ...] = ()) -> tuple[str, str]:
    """The query and system prompt of one Exa Agent run. Built ONLY from ``t.identifiers`` (public)."""
    ids = t.identifiers
    what = {"CRA": "CRA (Certificado de Recebíveis do Agronegócio)", "CRI": "CRI (Certificado de Recebíveis Imobiliários)",
            "debênture": "debênture", "FIP": "FIP (fundo de investimento em participações)"}.get(t.tipo, f"fundo ({t.tipo})")
    parts = [f"Documento oficial de {what}"]
    for k, label in (("codigo", "código"), ("isin", "ISIN"), ("cnpj_securitizadora", "CNPJ da securitizadora"),
                     ("issuer_cnpj", "CNPJ do emissor"), ("cnpj", "CNPJ"), ("nome_cvm", "nome na CVM")):
        if ids.get(k):
            parts.append(f"{label} {ids[k]}")
    want = "; ".join(f"{f}: {ex.FIELD_HINT[f]}" for f in fields)
    query = ", ".join(parts) + f". Encontre o documento de emissão ou o relatório mais recente e extraia: {want}."
    if phase == "official":
        scope = ("Use somente fontes oficiais: os domínios " + ", ".join(tuple(coordinator_domains) + OFFICIAL_DOMAINS)
                 + " e o site da própria emissora, securitizadora ou gestora. Não use ANBIMA Data nem agregadores.")
    else:
        scope = "Fontes oficiais não trouxeram o documento: busque na web aberta, preferindo documentos primários (PDF)."
    system = (scope + " Para cada fato devolva field, value copiado literalmente do documento, quote (trecho literal de "
              "40 a 400 caracteres que contém o valor), url do documento, document_date como impressa e document_title. "
              "Nunca calcule, converta ou resuma números. Sem fonte: não devolva o fato.")
    return query, system


def exa_output_schema(fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": list(fields)},
                        "value": {"type": "string"},
                        "quote": {"type": "string"},
                        "subject": {"type": ["string", "null"]},
                        "url": {"type": "string"},
                        "document_date": {"type": ["string", "null"]},
                        "document_title": {"type": ["string", "null"]},
                    },
                    "required": ["field", "value", "quote", "url"],
                },
            }
        },
        "required": ["facts"],
    }


# --- the section when the investigator does not run --------------------------------------------------

def not_run_section(reason_code: str = "investigador_desligado") -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "reason": "Investigador de documentos oficiais desligado nesta execução.",
        "reason_codes": [reason_code],
        "errors": [],
        "enabled": False,
        "limits": {"searches_per_trigger": PER_TRIGGER, "searches_per_report": PER_REPORT,
                   "max_documents_per_trigger": MAX_DOCS_PER_TRIGGER},
        "searches_used": 0,
        "searches_by_kind": {},
        "costs": _costs(None),
        "web_search": {"provider": "exa", "available": False, "note": None},
        "models": {"extractor": None, "judge": None, "tier_b_enabled": False, "note": None},
        "tiers": {k: TIER_LABEL[k] for k in (TIER_A, TIER_B, TIER_C)},
        "counts": {"triggers": 0, "facts": 0, "tier_a": 0, "tier_b": 0, "discarded": 0, "divergences": 0,
                   "documents_read": 0, "documents_not_read": 0},
        "triggers": [],
        "facts": [],
        "discarded": {"count": 0, "text": "0 fatos descartados", "by_reason": {}},
        "documents_consulted": [],
        "messages": [],
        "note": None,
    }


# --- production wiring (server.py) --------------------------------------------------------------------

INVESTIGATOR_ENV = "SILO_INVESTIGATOR"
EXA_KEY_ENV = "EXA_API_KEY"


def _costs(deps: InvestigatorDeps | None) -> dict[str, Any]:
    """The section's spend, all of it on the report's one meter (owner, #605 Q37): it is in X-Silo-Cost-Usd."""
    meter = getattr(getattr(deps, "models", None), "meter", None)
    roles = dict(getattr(meter, "by_role", {}) or {})
    llm_usd = sum(v for k, v in roles.items() if k != "investigator_exa")
    parent = getattr(meter, "parent", None)
    return {"usd": round(float(getattr(meter, "spent_usd", 0.0) or 0.0), 6),
            "llm_usd": round(llm_usd, 6),
            "exa_usd": round(roles.get("investigator_exa", 0.0), 6),
            "share_cap_usd": getattr(meter, "cap_usd", ex.INVESTIGATOR_SHARE_USD),
            "report_cap_usd": getattr(parent, "cap_usd", llm.COST_CAP_USD),
            "note": ("parte do teto único de US$1,00 do relatório (LLM do relatório, LLM do investigador e Exa); "
                     "incluído em X-Silo-Cost-Usd")}


def from_env(environ: dict[str, str] | None = None, meter: Any = None) -> Investigator | None:
    """The investigator the server runs when ``SILO_INVESTIGATOR=on``; ``None`` (section off) otherwise.

    Without ``EXA_API_KEY`` it degrades to Fundos.NET and RAD and says so; without an LLM key it reads the
    documents but extracts nothing, and says so. It never raises for a missing key.
    """
    import os

    from src.portfolio.investigator.cache import BundleDocumentCache
    from src.portfolio.investigator.sources import UrllibHttp

    env = os.environ if environ is None else environ
    if str(env.get(INVESTIGATOR_ENV) or "").strip().lower() not in ("on", "1", "true"):
        return None
    http = UrllibHttp(timeout=60.0)
    key = (env.get(EXA_KEY_ENV) or "").strip()
    share = ex.ShareMeter(meter)  # the investigator's share of the report's one meter (``meter``)
    exa = ExaClient(http, key, max_wait_s=90.0, meter=share) if key else None
    deps = InvestigatorDeps(http=http, cache=BundleDocumentCache(),
                            models=ex.models_from_env(env.get("SILO_LLM_PROVIDER"), share),
                            exa=exa, exa_note=None if exa else MSG_NO_EXA)
    return Investigator(deps)
