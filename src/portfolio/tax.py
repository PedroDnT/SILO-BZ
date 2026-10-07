"""Fee paid and tax per position (engine 1.11, issue #613).

Owner's resolution of #613 (grilling of 2026-10-05, Q21-Q27). The rules are the YAML files in
``src/portfolio/rules/tax/``, one per instrument type plus ``iof.yaml`` and ``person.yaml``, copied from
``docs/reference/research/tax-rules-by-instrument.md`` (#611) and never written from memory. The engine
records each file's sha256 in ``tax.rules_files``, as it does for ``indexer_rules.csv``.

What the block does, per statement line:

* **Fee paid in R$ per year**: the fee block's own headline (``fees.lines[].headline.per_year_brl``, the
  disclosed administration fee times the position value), never fetched again, labelled "estimativa". A range
  gives its two ends. Nothing is added for a fund of funds (its disclosed fee already includes the invested
  fund's, Art. 98). No performance-fee estimate. An ETF's fee is the third-party site's, labelled as such. A
  pension plan's loading fee only if the statement carries it (it never does today).
* **Tax**: the rate that applies today with its article, or "isento" with its article. The R$ estimate is that
  rate times the 12-month gain of the return block, labelled "estimativa", and only when the statement prints
  the application date, the date is on or before the window's base date, one rule applies and no condition the
  statement cannot show decides the rate. Without the date: the bracket ("alíquota entre X% e Y% conforme o
  prazo; data de aplicação não informada, a conferir") and no R$ figure. A date is never assumed. Come-cotas is a
  mark only.
* **PGBL and VGBL**: two columns, regressive and progressive, neither picked. PGBL is taxed on the whole
  redemption, VGBL on the income only; the option is irrevocable ("irretratável").
* **"Otimização"**: three factual kinds, each "informativo; não é recomendação": the next bracket change (only
  with the application date), the gross-up equivalence of an exempt product, X / (1 - alíquota), against the CDB
  bracket of the same term, and whether come-cotas applies. No imperative verb.
* **IOF**: only when the application date shows the position is under 30 days old.
* **Person level**: dividends and JCP flagged with their rule; the minimum tax as one line, no figure.

Every ``engine_cannot_observe`` item of a rule file is printed per position as "a conferir". The block makes no
tool call: it reads the statement, the fee block and the return block.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from src.portfolio.common import STATUS_COMPLETE, STATUS_PARTIAL, brl, iso, statement_source
from src.portfolio.identify import LineId

RULES_DIR = Path(__file__).parent / "rules" / "tax"
RULES_DIR_LABEL = "src/portfolio/rules/tax"
RULES_NOTE = "docs/reference/research/tax-rules-by-instrument.md"
SCHEMA = "silo.tax_rule/0.1"
NON_INSTRUMENT_FILES = ("iof", "person")
REQUIRED_KEYS = ("schema", "instrument", "label", "version", "valid_from", "valid_to", "position_date_checked",
                 "sources", "engine_cannot_observe", "not_verified")
REQUIRED_SOURCE_KEYS = ("id", "act", "article", "url", "accessed", "quote")

ESTIMATE_LABEL = "estimativa"
CHECK_LABEL = "a conferir"
INFO_LABEL = "informativo; não é recomendação"
EXEMPT_LABEL = "isento"
DATE_MISSING_TEXT = "alíquota entre {lo} e {hi} conforme o prazo; data de aplicação não informada, a conferir"
CANDIDATES_TEXT = "alíquota entre {lo} e {hi} conforme a regra que se aplica ({labels}); a conferir"
CANDIDATES_NO_DATE_TEXT = (
    "alíquota entre {lo} e {hi} conforme o prazo e a regra que se aplica ({labels}); data de aplicação não informada, "
    "a conferir"
)
REPRICING_TEXT = "alíquota entre {lo} e {hi} conforme o prazo médio de repactuação da carteira do ETF; a conferir"
REGIME_LABEL = "opção do participante; não informada"
# Per-line reader text (status, rate and instrument labels, the pension's fixed sentences) is the report's
# (src/portfolio/report/labels.py, engine 2.0); the block writes the codes and figures.
PENSION_BASE = {"PGBL": "valor total do resgate", "VGBL": "somente o rendimento"}
REGRESSIVE_NO_DATE = "tabela completa; data de início não informada, a conferir"
FUND_OF_FUNDS_NOTE = (
    "Nada somado pelos fundos investidos: a taxa divulgada de um fundo de fundos já inclui a do fundo investido "
    "(Art. 98, conforme a resolução de #613)."
)
PERFORMANCE_NOTE = "taxa de performance não estimada"
FEE_BASIS = "taxa de administração divulgada x valor da posição no extrato"
LOADING_TEXT = "taxa de carregamento: não impressa no extrato; não incluída"
NO_FEE_TEXT = "sem taxa de administração (ação, título ou crédito direto)"
SECTION_NOTE = (
    "Fatos por posição a partir das regras de imposto versionadas do SILO, cada uma com artigo e citação. Valores em R$ são "
    "estimativas; nenhuma linha é recomendação. Sem total de imposto da carteira."
)
NOT_COVERED = [
    {"tipo": "tesouro", "text": "Tesouro Direto: o SILO ainda não tem regra de imposto para o título público."},
    {"tipo": "FIDC", "text": "FIDC: fora das regras de imposto do SILO; sem regra."},
    {"tipo": "FIP", "text": "FIP: fora das regras de imposto do SILO; sem regra."},
]
# Reason codes of this block (their fixed text is in common.REASON_TEXT).
R_NO_RULE = "imposto_sem_regra"
R_LINES_NO_RULE = "imposto_linhas_sem_regra"
R_NO_DATE = "data_aplicacao_nao_informada"
R_CONDITION = "aliquota_depende_de_condicao"
R_MANY_RULES = "mais_de_uma_regra"
R_NO_GAIN = "ganho_12m_indisponivel"
R_INSIDE_WINDOW = "aplicacao_dentro_da_janela"
R_GAIN_NOT_POSITIVE = "ganho_12m_nao_positivo"
R_PENSION = "previdencia_sem_estimativa"
R_EXEMPT = "isento_sem_imposto"

CENT4 = Decimal("0.0001")


# ---------------------------------------------------------------------------
# Rule files.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleFile:
    name: str  # file stem
    data: dict
    sha256: str

    @property
    def label(self) -> str:
        return self.data["label"]

    @property
    def file(self) -> str:
        return f"{RULES_DIR_LABEL}/{self.name}.yaml"

    def source(self, sid: str) -> dict[str, Any]:
        for s in self.data["sources"]:
            if s["id"] == sid:
                return {"rules_file": self.file, "source_id": sid, "act": s["act"], "article": s["article"],
                        "url": s["url"], "quote": s["quote"]}
        raise KeyError(f"{self.name}: unknown source id {sid!r}")

    def article(self, sid: str) -> str:
        s = self.source(sid)
        return f"{s['act']}, {s['article']}"

    def primary(self) -> dict:
        return next(e for e in self.data["ir"]["events"] if e.get("primary"))

    def cannot_observe(self, plan: str | None = None) -> list[dict]:
        out = []
        for item in self.data.get("engine_cannot_observe") or []:
            plans = item.get("plans")
            if plans and plan and plan.lower() not in plans:
                continue
            out.append(item)
        return out


def _source_ids(node: Any) -> set[str]:
    """Every value of a key named ``source`` or ``*_source`` anywhere under ``node``."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if (k == "source" or k.endswith("_source")) and isinstance(v, str):
                out.add(v)
            else:
                out |= _source_ids(v)
    elif isinstance(node, list):
        for v in node:
            out |= _source_ids(v)
    return out


def load_rules(rules_dir: Path = RULES_DIR) -> dict[str, RuleFile]:
    """Every rule file, validated: required keys, every source complete, every cited source id defined."""
    out: dict[str, RuleFile] = {}
    for path in sorted(rules_dir.glob("*.yaml")):
        raw = path.read_bytes()
        data = yaml.safe_load(raw)
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            raise ValueError(f"{path.name}: missing key(s) {missing}")
        if data["schema"] != SCHEMA:
            raise ValueError(f"{path.name}: schema {data['schema']!r}, expected {SCHEMA!r}")
        if data["instrument"] != path.stem:
            raise ValueError(f"{path.name}: instrument {data['instrument']!r} is not the file stem")
        ids = set()
        for s in data["sources"]:
            gaps = [k for k in REQUIRED_SOURCE_KEYS if not s.get(k)]
            if gaps:
                raise ValueError(f"{path.name}: source {s.get('id')!r} lacks {gaps}")
            ids.add(s["id"])
        if path.stem not in NON_INSTRUMENT_FILES:
            if "ir" not in data or "iof" not in data:
                raise ValueError(f"{path.name}: an instrument file needs 'ir' and 'iof'")
            if sum(1 for e in data["ir"]["events"] if e.get("primary")) != 1:
                raise ValueError(f"{path.name}: exactly one primary IR event")
        unknown = _source_ids({k: v for k, v in data.items() if k != "sources"}) - ids
        if unknown:
            raise ValueError(f"{path.name}: cites undefined source id(s) {sorted(unknown)}")
        out[path.stem] = RuleFile(path.stem, data, hashlib.sha256(raw).hexdigest())
    return out


def in_force(rf: RuleFile, on: dt.date) -> bool:
    """The file's [valid_from, valid_to] covers ``on``. A year-only valid_from covers the whole year after it."""
    vf = str(rf.data["valid_from"])
    if re.fullmatch(r"\d{4}", vf):
        ok_from = int(vf) <= on.year
    else:
        ok_from = dt.date.fromisoformat(vf) <= on
    vt = rf.data.get("valid_to")
    ok_to = vt is None or on <= dt.date.fromisoformat(str(vt))
    return ok_from and ok_to


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def pct_text(rate: Any) -> str:
    """0.225 -> '22,5%'; 0.2 -> '20%' (Brazilian form, as the law prints it)."""
    v = (_d(rate) * 100).normalize()
    return format(v, "f").replace(".", ",") + "%"


def _pct(rate: Any) -> float:
    return float((_d(rate) * 100).quantize(CENT4, rounding=ROUND_HALF_UP))


def _num_text(x: Decimal, places: int = 2) -> str:
    q = Decimal(1).scaleb(-places)
    return format(x.quantize(q, rounding=ROUND_HALF_UP), "f").replace(".", ",")


def _add(d: dt.date, n: int, unit: str) -> dt.date:
    if unit == "days":
        return d + dt.timedelta(days=n)
    months = n if unit == "months" else 12 * n
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _strip(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _rows(rate: dict) -> list[dict]:
    return list(rate.get("rows") or [])


def _row_today(rows: list[dict], unit: str, start: dt.date, today: dt.date) -> int:
    for i, r in enumerate(rows):
        if r["max"] is None or today <= _add(start, int(r["max"]), unit):
            return i
    return len(rows) - 1


def _all_rates(rate: dict) -> list[Decimal]:
    t = rate["table"]
    if t == "fixed":
        return [_d(rate["rate"])]
    if t == "progressive":
        return [_d(rate["advance_rate"])]
    out = [_d(r["rate"]) for r in _rows(rate)]
    if rate.get("breach_rate") is not None:
        out.append(_d(rate["breach_rate"]))
    return out


# ---------------------------------------------------------------------------
# Which rule file(s) a line takes.
# ---------------------------------------------------------------------------

DIRECT = {"CDB": "cdb", "LCI": "lci", "LCA": "lca", "CRI": "cri", "CRA": "cra", "FII": "fii", "ação": "shares"}


def _pension_plan(p) -> str | None:
    # the plan is read from the statement's table heading only (estrategia_corretora), never from the fund's name
    m = re.search(r"\b(PGBL|VGBL)\b", p.estrategia_corretora or "", re.I)
    return m.group(1).upper() if m else None


def _is_pension(p) -> bool:
    return (p.classe_corretora or "") == "Previdência" or (p.estrategia_corretora or "").startswith("Previdência")


def select(li: LineId, fee_line: dict | None, ret_line: dict | None) -> tuple[list[str], str | None]:
    """(candidate rule files, why). Read only from facts already in the engine; never from a name."""
    p = li.position
    if _is_pension(p):
        return ["pension_regressive", "pension_progressive"], "linha de previdência (PGBL ou VGBL) no extrato"
    if p.tipo in DIRECT:
        return [DIRECT[p.tipo]], None
    if p.tipo == "outro" and li.asset_class == "equity":
        return ["shares"], "linha 'outro' identificada como ação"
    if p.tipo == "debênture":
        return ["debenture", "debenture_incentivized"], (
            "o extrato não diz se a debênture é incentivada (Lei 12.431) ou comum; a de infraestrutura da Lei 14.801 "
            "é comum para a pessoa física"
        )
    if p.tipo == "ETF":
        basis = (ret_line or {}).get("basis")
        if basis == "last_price_etf_renda_fixa":
            return ["etf_fixed_income"], "ETF só no registro de ETFs, fora da fita à vista da B3: ETF de renda fixa"
        if basis == "close_sem_proventos":
            return ["etf_equity"], "ETF na fita à vista da B3 (ETFs de renda fixa não estão nela)"
        return ["etf_equity", "etf_fixed_income"], "o extrato e o SILO não dizem se o ETF é de ações ou de renda fixa"
    if p.tipo == "fundo":
        terms = ((fee_line or {}).get("disclosed") or {}).get("terms_as_filed") or {}
        classe = terms.get("classe_anbima") or ""
        if classe.startswith("Ações"):
            return ["fund_equity"], f"classe ANBIMA '{classe}' arquivada no Extrato da CVM"
        return ["fund_long", "fund_short"], "o extrato não diz se o fundo é de longo ou de curto prazo"
    for nc in NOT_COVERED:
        if nc["tipo"] == p.tipo:
            return [], nc["text"]
    return [], f"tipo '{p.tipo}' sem regra na nota #611"


# ---------------------------------------------------------------------------
# Fee paid in R$ per year.
# ---------------------------------------------------------------------------


def _fee(li: LineId, fee_line: dict | None, pension: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": None,
        "label": ESTIMATE_LABEL,
        "basis": FEE_BASIS,
        "kind": None,
        "rate_pct_year": None,
        "per_year_brl": None,
        "rate_min_pct_year": None,
        "rate_max_pct_year": None,
        "per_year_min_brl": None,
        "per_year_max_brl": None,
        "third_party": False,
        "fee_status": None,
        "notes": [],
        "loading": {"status": "nao_informado", "text": LOADING_TEXT} if pension else None,
        "sources": [],
    }
    if fee_line is None:
        out["status"] = "nao_se_aplica"
        out["fee_status"] = NO_FEE_TEXT
        out["basis"] = None
        return out
    h = fee_line.get("headline") or {}
    out["kind"] = h.get("kind")
    out["fee_status"] = fee_line.get("fee_status")
    out["sources"] = list(h.get("sources") or [])
    out["notes"] = [FUND_OF_FUNDS_NOTE, PERFORMANCE_NOTE]
    kind = h.get("kind")
    usable = kind in ("fixa", "lamina_mais_recente") or (kind == "etf_site" and h.get("counted_as_cost"))
    if usable and h.get("per_year_brl") is not None:
        out["status"] = "estimada"
        out["rate_pct_year"] = h.get("rate_pct_year")
        out["per_year_brl"] = h.get("per_year_brl")
        if kind == "etf_site":
            out["third_party"] = True
    elif kind == "faixa" and h.get("per_year_min_brl") is not None:
        out["status"] = "faixa"
        out["rate_min_pct_year"] = h.get("rate_min_pct_year")
        out["rate_max_pct_year"] = h.get("rate_max_pct_year")
        out["per_year_min_brl"] = h.get("per_year_min_brl")
        out["per_year_max_brl"] = h.get("per_year_max_brl")
    else:
        out["status"] = "sem_taxa"
    return out


# ---------------------------------------------------------------------------
# Tax per candidate rule file.
# ---------------------------------------------------------------------------


def _candidate(rf: RuleFile, start: dt.date | None, today: dt.date) -> dict[str, Any]:
    ev = rf.primary()
    rate = ev["rate"]
    rates = _all_rates(rate)
    today_rate: Decimal | None = None
    nxt: dict | None = None
    if rate["table"] == "fixed":
        today_rate = rates[0]
    elif rate["table"] == "holding" and start is not None:
        rows, unit = _rows(rate), rate["unit"]
        i = _row_today(rows, unit, start, today)
        today_rate = _d(rows[i]["rate"])
        if i + 1 < len(rows):
            change = _add(start, int(rows[i]["max"]), unit) + dt.timedelta(days=1)
            nxt = {"date": change, "days": (change - today).days, "from": today_rate, "to": _d(rows[i + 1]["rate"])}
    return {
        "instrument": rf.name,
        "label": rf.label,
        "rules_file": rf.file,
        "event": ev["event"],
        "base": ev.get("base"),
        "exempt": bool(ev.get("exempt")),
        "table": rate["table"],
        "unit": rate.get("unit"),
        "rates_pct": [_pct(r) for r in rates],
        "rate_today_pct": _pct(today_rate) if today_rate is not None else None,
        "article": rf.article(ev["source"]),
        "rule_source": rf.source(ev["source"]),
        "_today": today_rate,
        "_rates": rates,
        "_next": nxt,
        "_decides": [c for c in rf.cannot_observe() if c.get("decides_rate")],
    }


def _public(c: dict) -> dict:
    return {k: v for k, v in c.items() if not k.startswith("_")}


def _other_events(rf: RuleFile) -> list[dict]:
    out = []
    for ev in rf.data["ir"]["events"]:
        if ev.get("primary"):
            continue
        r = ev["rate"]
        out.append({"event": ev["event"], "rates_pct": [_pct(x) for x in _all_rates(r)],
                    "article": rf.article(ev["source"]), "rule_source": rf.source(ev["source"])})
    for ex in rf.data["ir"].get("exemptions") or []:
        sid = ex.get("source") or (ex.get("all_of") or [{}])[0].get("source")
        out.append({"event": f"isenção ({ex.get('applies_to')})", "text": ex.get("label"), "rates_pct": [0.0],
                    "article": rf.article(sid), "rule_source": rf.source(sid)})
    no_ex = rf.data["ir"].get("no_exemption")
    if no_ex:
        out.append({"event": "sem isenção", "text": no_ex["label"], "rates_pct": None,
                    "article": rf.article(no_ex["source"]), "rule_source": rf.source(no_ex["source"])})
    return out


def _come_cotas(rf: RuleFile) -> dict[str, Any] | None:
    ir = rf.data["ir"]
    per = ir.get("periodic")
    psrc = ir.get("periodic_source")
    if isinstance(per, dict):
        return {"applies": True, "rate_pct": _pct(per["rate"]),
                "text": f"come-cotas: sim, {pct_text(per['rate'])} no último dia útil de maio e de novembro ({rf.label})",
                "article": rf.article(per["source"]), "rule_source": rf.source(per["source"])}
    if per == "conditional":
        return {"applies": None, "rate_pct": None,
                "text": f"come-cotas: depende de o fundo ser entidade de investimento; {CHECK_LABEL} ({rf.label})",
                "article": rf.article(psrc), "rule_source": rf.source(psrc)}
    if psrc:
        return {"applies": False, "rate_pct": None, "text": f"come-cotas: não se aplica ({rf.label})",
                "article": rf.article(psrc), "rule_source": rf.source(psrc)}
    return None


# ---------------------------------------------------------------------------
# Optimization facts.
# ---------------------------------------------------------------------------

_PCT_CDI = re.compile(r"^(\d+(?:[.,]\d+)?)\s*% do cdi$")
_PCT_AA = re.compile(r"^(\d+(?:[.,]\d+)?)\s*% a\.? ?a\.?$")


def _gross_up(rules: dict[str, RuleFile], p, start: dt.date | None) -> dict[str, Any]:
    cdb = rules["cdb"]
    ev = cdb.primary()
    rows = _rows(ev["rate"])
    taxa = p.taxa_texto
    norm = _strip(taxa or "")
    m_cdi, m_aa = _PCT_CDI.match(norm), _PCT_AA.match(norm)
    x = _d((m_cdi or m_aa).group(1).replace(",", ".")) if (m_cdi or m_aa) else None
    unit_txt = "% do CDI" if m_cdi else "% a.a."

    def one(rate: Decimal) -> dict:
        factor = Decimal(1) / (Decimal(1) - rate)
        eq = (x * factor) if x is not None else None
        return {"cdb_rate_pct": _pct(rate), "factor": float(factor.quantize(CENT4, rounding=ROUND_HALF_UP)),
                "equivalent_pct": float(eq.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if eq is not None else None,
                "equivalent_text": f"{_num_text(eq)}{unit_txt}" if eq is not None else None}

    term_days = (p.vencimento - start).days if (p.vencimento and start) else None
    if term_days is not None:
        i = _row_today(rows, "days", start, p.vencimento)
        brackets = [one(_d(rows[i]["rate"]))]
        scope = f"prazo de {term_days} dias da aplicação ao vencimento"
    else:
        brackets = [one(_d(r["rate"])) for r in rows]
        scope = "data de aplicação ou vencimento não informados: as quatro faixas do CDB"
    if x is not None:
        body = "; ".join(f"{b['equivalent_text']} na faixa de {pct_text(_d(b['cdb_rate_pct']) / 100)}" for b in brackets)
        text = f"isento a {taxa} equivale a um CDB tributado de {body} (X / (1 - alíquota); {scope})"
    else:
        body = "; ".join(f"fator {_num_text(_d(b['factor']), 4)} na faixa de {pct_text(_d(b['cdb_rate_pct']) / 100)}"
                         for b in brackets)
        shown = f"a taxa impressa ({taxa}) não é convertida" if taxa else "sem taxa impressa no extrato"
        text = f"equivalência bruta X / (1 - alíquota): {body}; {shown} ({scope})"
    return {"kind": "equivalencia_bruta", "label": INFO_LABEL, "exempt_rate_text": taxa, "term_days": term_days,
            "brackets": brackets, "text": text, "article": cdb.article(ev["source"]), "rule_source": cdb.source(ev["source"])}


def _next_bracket(c: dict, many: bool) -> dict[str, Any] | None:
    n = c["_next"]
    if not n:
        return None
    who = f" ({c['label']})" if many else ""
    text = f"em {n['days']} dias a alíquota cai de {pct_text(n['from'])} para {pct_text(n['to'])}{who}"
    return {"kind": "proxima_faixa", "label": INFO_LABEL, "instrument": c["instrument"], "date": iso(n["date"]),
            "days": n["days"], "from_pct": _pct(n["from"]), "to_pct": _pct(n["to"]), "text": text,
            "article": c["article"], "rule_source": c["rule_source"]}


# ---------------------------------------------------------------------------
# IOF.
# ---------------------------------------------------------------------------


def _iof(rules: dict[str, RuleFile], cands: list[RuleFile], start: dt.date | None, today: dt.date) -> dict | None:
    iof = rules["iof"]
    table = iof.data["rules"]["iof_30_day_table"]
    if start is None or not cands:
        return None
    days = (today - start).days
    if days >= int(table["window_days"]):
        return None
    kinds = {rf.data["iof"]["rule"] for rf in cands}
    if kinds <= {"zero_rate"}:
        z = iof.data["rules"]["zero_rate"]
        return {"days_held": days, "rate_pct": 0.0 if z.get("zero_rate") else None, "text": z["text"], "article": iof.article(z["source"]),
                "rule_source": iof.source(z["source"])}
    if "iof_30_day_table" in kinds:
        return {"days_held": days, "rate_pct": None, "text": table["text"], "article": iof.article(table["source"]),
                "rule_source": iof.source(table["source"])}
    return None


# ---------------------------------------------------------------------------
# One line.
# ---------------------------------------------------------------------------


def _gain_12m(ret_line: dict | None) -> tuple[Decimal | None, dict | None]:
    w = ((ret_line or {}).get("windows") or {}).get("12m") or {}
    if w.get("status") != "avaliado" or w.get("net_return_pct") is None:
        return None, None
    return _d(w["net_return_pct"]), w


def _estimate(li: LineId, cand: dict, ret_line: dict | None, start: dt.date | None) -> dict[str, Any]:
    out: dict[str, Any] = {"label": ESTIMATE_LABEL, "tax_brl": None, "gain_12m_brl": None, "net_return_12m_pct": None,
                           "rate_pct": cand["rate_today_pct"],
                           "basis": "alíquota de hoje x ganho de 12 meses do bloco de retorno (valor x r / (1 + r))",
                           "reason_code": None, "reason": None, "sources": []}
    r, w = _gain_12m(ret_line)
    if r is None:
        out["reason_code"], out["reason"] = R_NO_GAIN, "sem retorno de 12 meses avaliado para a linha"
        return out
    base = dt.date.fromisoformat(w["base_date"]) if w.get("base_date") else None
    if base is None or start is None or start > base:
        out["reason_code"] = R_INSIDE_WINDOW
        out["reason"] = "aplicação depois do início da janela de 12 meses: o ganho da janela não é o da posição"
        return out
    value = li.position.valor
    gain = value * (r / 100) / (1 + r / 100)
    out["net_return_12m_pct"] = float(r)
    out["gain_12m_brl"] = brl(gain)
    out["sources"] = list((ret_line or {}).get("sources") or [])
    if gain <= 0:
        out["reason_code"], out["reason"] = R_GAIN_NOT_POSITIVE, "ganho de 12 meses não positivo: nenhum imposto estimado"
        return out
    out["tax_brl"] = brl(gain * cand["_today"])
    return out


def _no_estimate(code: str, reason: str) -> dict[str, Any]:
    return {"label": ESTIMATE_LABEL, "tax_brl": None, "gain_12m_brl": None, "net_return_12m_pct": None,
            "rate_pct": None, "basis": None, "reason_code": code, "reason": reason, "sources": []}


def _pension(rules: dict[str, RuleFile], p, start: dt.date | None, today: dt.date) -> dict[str, Any]:
    reg, prog = rules["pension_regressive"], rules["pension_progressive"]
    plan = _pension_plan(p)
    rev = reg.primary()
    rrows = _rows(rev["rate"])
    table = [{"over_years": r["min"], "up_to_years": r["max"], "rate_pct": _pct(r["rate"])} for r in rrows]
    regressive: dict[str, Any] = {"table": table, "rate_today_pct": None, "text": REGRESSIVE_NO_DATE,
                                  "definitive": True, "article": reg.article(rev["source"]),
                                  "rule_source": reg.source(rev["source"])}
    if start is not None:
        c = _candidate(reg, start, today)
        regressive["rate_today_pct"] = c["rate_today_pct"]
        regressive["text"] = (f"{pct_text(c['_today'])} para aportes feitos em {start.isoformat()}; cada aporte conta o "
                              f"próprio prazo de acumulação, a conferir")
    pev = prog.primary()
    progressive = {"advance_rate_pct": _pct(pev["rate"]["advance_rate"]), "text": pev["rate"]["text"],
                   "definitive": False, "article": prog.article(pev["source"]), "rule_source": prog.source(pev["source"]),
                   "annual_table_rule_source": prog.source(pev["rate"]["annual_table_source"])}
    return {
        "plan": plan,
        "plan_source": "título da tabela de previdência no extrato" if plan else None,
        "regime": None,
        "base": PENSION_BASE.get(plan or "") if plan else None,
        "base_rule_source": reg.source(rev["base_source"]),
        "regressive": regressive,
        "progressive": progressive,
        "irrevocable": True,
        "irrevocable_rule_source": reg.source(reg.data["ir"]["option"]["source"]),
    }


def _line(li: LineId, rules: dict[str, RuleFile], fee_line: dict | None, ret_line: dict | None,
          today: dt.date) -> dict[str, Any]:
    p = li.position
    start = p.data_aplicacao
    names, why = select(li, fee_line, ret_line)
    pension = names[:1] == ["pension_regressive"]
    cands_rf = [rules[n] for n in names if n in rules and in_force(rules[n], today)]
    not_in_force = [n for n in names if n in rules and not in_force(rules[n], today)]
    a_conferir: list[dict] = []
    seen: set[str] = set()
    plan = _pension_plan(p) if pension else None
    for rf in cands_rf:
        for item in rf.cannot_observe(plan):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            a_conferir.append({"id": item["id"], "text": item["text"], "label": CHECK_LABEL,
                               "decides_rate": bool(item.get("decides_rate")), "rules_file": rf.file})
    out: dict[str, Any] = {
        "line_no": p.line_no,
        "linha_extrato": p.linha_extrato,
        "tipo": p.tipo,
        "valor_brl": brl(p.valor),
        "fee": _fee(li, fee_line, pension),
        "holding": {
            "data_aplicacao": iso(start),
            "days_held": (today - start).days if start else None,
            "text": None if start else "data de aplicação não informada no extrato",
            "sources": [statement_source(p.line_no, p.data_posicao)] if start else [],
        },
        "tax": None,
        "pension": None,
        "optimization": [],
        "iof": None,
        "a_conferir": a_conferir,
        "sources": [statement_source(p.line_no, p.data_posicao)],
    }
    tax: dict[str, Any] = {
        "status": None, "selection_reason": why,
        "instrument": None, "rules_file": None,
        "candidates": [], "rate_today_pct": None, "exempt": False,
        "article": None, "rule_source": None, "bracket": None, "outcomes": None,
        "other_events": [], "come_cotas": [], "estimate": None, "reason_code": None, "reason": None,
    }
    out["tax"] = tax
    if not cands_rf:
        tax["status"] = "sem_regra"
        tax["reason_code"] = R_NO_RULE
        tax["reason"] = why if not not_in_force else f"regra fora de vigência na data da posição: {', '.join(not_in_force)}"
        tax["estimate"] = _no_estimate(R_NO_RULE, tax["reason"])
        return out

    for rf in cands_rf:
        cc = _come_cotas(rf)
        if cc:
            tax["come_cotas"].append(cc)
    if pension:
        tax["status"] = "previdencia"
        tax["candidates"] = [_public(_candidate(rf, start, today)) for rf in cands_rf]
        tax["estimate"] = _no_estimate(R_PENSION, "previdência: regime não informado; sem estimativa em R$")
        out["pension"] = _pension(rules, p, start, today)
        reg = _candidate(rules["pension_regressive"], start, today)
        nb = _next_bracket(reg, False)
        if nb:
            nb["text"] = f"regime regressivo, para aportes feitos na data informada: {nb['text']}"
            out["optimization"].append(nb)
        for cc in tax["come_cotas"]:
            out["optimization"].append({"kind": "come_cotas", "label": INFO_LABEL, **cc})
        return out

    cands = [_candidate(rf, start, today) for rf in cands_rf]
    tax["candidates"] = [_public(c) for c in cands]
    many = len(cands) > 1
    for c in cands:
        nb = _next_bracket(c, many)
        if nb:
            out["optimization"].append(nb)
    if not many:
        c, rf = cands[0], cands_rf[0]
        tax.update(instrument=rf.name, rules_file=rf.file, article=c["article"],
                   rule_source=c["rule_source"], other_events=_other_events(rf))
        if c["exempt"] and not c["_decides"]:
            tax.update(status="isento", exempt=True, rate_today_pct=0.0)
            tax["estimate"] = _no_estimate(R_EXEMPT, "isento: nenhum imposto de renda")
            out["optimization"].append(_gross_up(rules, p, start))
        elif c["table"] == "fund_repricing_term":
            lo, hi = min(c["_rates"]), max(c["_rates"])
            tax.update(status="faixa",
                       bracket={"min_pct": _pct(lo), "max_pct": _pct(hi),
                                "text": REPRICING_TEXT.format(lo=pct_text(lo), hi=pct_text(hi))})
            tax["estimate"] = _no_estimate(R_CONDITION, "a alíquota depende do prazo médio da carteira do ETF")
        elif c["_today"] is None:
            lo, hi = min(c["_rates"]), max(c["_rates"])
            tax.update(status="faixa",
                       bracket={"min_pct": _pct(lo), "max_pct": _pct(hi),
                                "text": DATE_MISSING_TEXT.format(lo=pct_text(lo), hi=pct_text(hi))})
            tax["estimate"] = _no_estimate(R_NO_DATE, "data de aplicação não informada: sem valor em R$")
            if not any(a["id"] == "data_aplicacao" for a in a_conferir):
                a_conferir.insert(0, {"id": "data_aplicacao", "text": "data de aplicação não informada no extrato",
                                      "label": CHECK_LABEL, "decides_rate": True, "rules_file": None})
        else:
            tax["rate_today_pct"] = c["rate_today_pct"]
            if c["_decides"]:
                tax["status"] = "condicional"
                tax["outcomes"] = [f"{pct_text(c['_today'])} ({c['article']})"] + [d["text"] for d in c["_decides"]]
                tax["estimate"] = _no_estimate(R_CONDITION, "a alíquota depende de condição que o extrato não mostra")
            else:
                tax["status"] = "aliquota_hoje"
                if start is None:
                    tax["estimate"] = _no_estimate(R_NO_DATE, "data de aplicação não informada: sem valor em R$")
                else:
                    tax["estimate"] = _estimate(li, c, ret_line, start)
    else:
        rates = [r for c in cands for r in ([c["_today"]] if c["_today"] is not None else c["_rates"])]
        lo, hi = min(rates), max(rates)
        labels = " ou ".join(c["label"] for c in cands)
        tax.update(status="candidatos",
                   bracket={"min_pct": _pct(lo), "max_pct": _pct(hi),
                            "text": (CANDIDATES_NO_DATE_TEXT if start is None and any(c["table"] == "holding" for c in cands)
                                     else CANDIDATES_TEXT).format(lo=pct_text(lo), hi=pct_text(hi), labels=labels)})
        tax["estimate"] = _no_estimate(R_MANY_RULES, f"mais de uma regra possível ({labels}): sem valor em R$")
        if start is None and any(c["table"] == "holding" for c in cands) and not any(a["id"] == "data_aplicacao" for a in a_conferir):
            a_conferir.insert(0, {"id": "data_aplicacao", "text": "data de aplicação não informada no extrato",
                                  "label": CHECK_LABEL, "decides_rate": True, "rules_file": None})
    for cc in tax["come_cotas"]:
        out["optimization"].append({"kind": "come_cotas", "label": INFO_LABEL, **cc})
    out["iof"] = _iof(rules, cands_rf, start, today)
    return out


# ---------------------------------------------------------------------------
# Person level.
# ---------------------------------------------------------------------------


def _person(rules: dict[str, RuleFile], lines: list[LineId]) -> dict[str, Any]:
    rf = rules["person"]
    r = rf.data["rules"]
    flags = []
    for key in ("dividends", "jcp"):
        rule = r[key]
        nos = [li.line_no for li in lines if li.position.tipo in rule["applies_to_tipos"]
               or (li.position.tipo == "outro" and li.asset_class == "equity")]
        flags.append({"id": key, "line_nos": nos, "flagged": bool(nos), "rate_pct": _pct(rule["rate"]),
                      "text": rule["text"], "article": rf.article(rule["source"]), "rule_source": rf.source(rule["source"]),
                      "computed": False})
    mt = r["minimum_tax"]
    return {
        "flags": flags,
        "minimum_tax": {"text": mt["text"], "computed": False, "excluded_income": list(mt["excluded_income"]),
                        "article": rf.article(mt["source"]), "rule_source": rf.source(mt["source"]),
                        "excluded_income_rule_source": rf.source(mt["excluded_income_source"])},
        "a_conferir": [{"id": i["id"], "text": i["text"], "label": CHECK_LABEL, "rules_file": rf.file}
                       for i in rf.cannot_observe()],
        "rules_file": rf.file,
    }


# ---------------------------------------------------------------------------
# The block.
# ---------------------------------------------------------------------------


def compute_tax(lines: list[LineId], fees: dict[str, Any], returns: dict[str, Any], position_date: dt.date,
                rules_dir: Path = RULES_DIR) -> dict[str, Any]:
    rules = load_rules(rules_dir)
    fee_by = {ln["line_no"]: ln for ln in fees.get("lines") or []}
    ret_by = {ln["line_no"]: ln for ln in returns.get("lines") or []}
    out_lines = [_line(li, rules, fee_by.get(li.line_no), ret_by.get(li.line_no), position_date) for li in lines]
    no_rule = [ln for ln in out_lines if ln["tax"]["status"] == "sem_regra"]
    status = STATUS_PARTIAL if no_rule else STATUS_COMPLETE
    return {
        "status": status,
        "reason": "Há linhas sem regra de imposto; cada linha informa o motivo." if no_rule else None,
        "errors": [],
        "reason_codes": [R_LINES_NO_RULE] if no_rule else [],
        "position_date": iso(position_date),
        "note": SECTION_NOTE,
        "labels": {"estimate": ESTIMATE_LABEL, "check": CHECK_LABEL, "info": INFO_LABEL, "exempt": EXEMPT_LABEL,
                   "date_missing": DATE_MISSING_TEXT, "regime": REGIME_LABEL},
        "rules_note": RULES_NOTE,
        "rules_files": [{"file": rf.file, "instrument": rf.name, "version": rf.data["version"],
                         "valid_from": str(rf.data["valid_from"]), "valid_to": rf.data["valid_to"],
                         "in_force": in_force(rf, position_date), "sha256": rf.sha256,
                         "not_verified": list(rf.data.get("not_verified") or [])}
                        for rf in rules.values()],
        "not_covered": NOT_COVERED,
        "lines": out_lines,
        "person": _person(rules, lines),
        "n_lines": len(out_lines),
        "n_with_rule": len(out_lines) - len(no_rule),
        "n_without_rule": len(no_rule),
        "n_tax_estimated": sum(1 for ln in out_lines if (ln["tax"].get("estimate") or {}).get("tax_brl") is not None),
        "n_fee_estimated": sum(1 for ln in out_lines if ln["fee"]["status"] == "estimada"),
    }
