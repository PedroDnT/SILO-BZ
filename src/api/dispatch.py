"""Map (entity, doc_type) pairs to CVMIngestor methods.

Three calling conventions exist in `src.pipeline.cvm_pipeline.CVMIngestor`:

    monthly       — method(year, month)             needs year + month
    yearly_doc    — method(doc_type_arg, year)      needs year, doc_type passed as kwarg
    yearly_instr  — method(instrument_type_arg, year)  same shape, kept distinct for clarity

`resolve()` returns a zero-arg coroutine factory the caller can spawn under
`asyncio.run()` — the routes layer doesn't need to know the convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple

# (entity, doc_type) -> (method_name, convention, [extra_arg])
# `extra_arg` is the literal string the underlying method expects (e.g. the
# raw CVM doc_type key like "mensal_geral"). When the API doc_type already
# matches the underlying arg, this is just the doc_type itself.
_TABLE: Dict[Tuple[str, str], Tuple[str, str, Optional[str], str]] = {
    # FI monthly — (year, month)                                      target table
    ("fi", "diario"):                ("ingest_fi_diario",        "monthly",      None, "cvm_fi_diario"),
    ("fi", "cda"):                   ("ingest_fi_cda",           "monthly",      None, "cvm_fi_cda"),
    ("fi", "perfil"):                ("ingest_fi_perfil",        "monthly",      None, "cvm_fi_perfil"),
    ("fi", "balancete"):             ("ingest_fi_balancete",     "monthly",      None, "cvm_fi_balancete"),

    # FIDC monthly
    ("fidc", "mensal"):              ("ingest_fidc_mensal",        "monthly",    None, "cvm_fidc_mensal"),
    ("fidc", "tranche"):             ("ingest_fidc_tranche",       "monthly",    None, "cvm_fidc_tranche"),
    ("fidc", "tranche_flows"):       ("ingest_fidc_tranche_flows", "monthly",    None, "cvm_fidc_tranche_flows"),
    ("fidc", "aging"):               ("ingest_fidc_aging",         "monthly",    None, "cvm_fidc_aging"),

    # FIAGRO monthly
    ("fiagro", "mensal"):            ("ingest_fiagro_mensal",      "monthly",    None, "cvm_fiagro_mensal"),

    # FIP yearly (doc_type passed through to method)
    ("fip", "inf_trimestral"):       ("ingest_fip_periodic", "yearly_doc",      "inf_trimestral",     "cvm_fip_periodic"),
    ("fip", "inf_quadrimestral"):    ("ingest_fip_periodic", "yearly_doc",      "inf_quadrimestral",  "cvm_fip_periodic"),

    # FII yearly
    ("fii", "mensal_geral"):           ("ingest_fii_mensal",   "yearly_doc",   "mensal_geral",           "cvm_fii_mensal"),
    ("fii", "mensal_ativo_passivo"):   ("ingest_fii_mensal",   "yearly_doc",   "mensal_ativo_passivo",   "cvm_fii_mensal"),
    ("fii", "mensal_complemento"):     ("ingest_fii_mensal",   "yearly_doc",   "mensal_complemento",     "cvm_fii_mensal"),
    ("fii", "trimestral"):             ("ingest_fii_periodic", "yearly_doc",   "trimestral",             "cvm_fii_periodic"),
    ("fii", "anual"):                  ("ingest_fii_periodic", "yearly_doc",   "anual",                  "cvm_fii_periodic"),
    ("fii", "dfin"):                   ("ingest_fii_periodic", "yearly_doc",   "dfin",                   "cvm_fii_periodic"),

    # SECURIT yearly
    ("securit", "cra_mensal"):       ("ingest_securit_mensal", "yearly_instr", "cra_mensal", "cvm_securit_mensal"),
    ("securit", "cri_mensal"):       ("ingest_securit_mensal", "yearly_instr", "cri_mensal", "cvm_securit_mensal"),
    ("securit", "ots_mensal"):       ("ingest_securit_mensal", "yearly_instr", "ots_mensal", "cvm_securit_mensal"),
    ("securit", "cra_classe"):       ("ingest_securit_serie",  "yearly_doc",   "cra_classe", "cvm_securit_serie"),
    ("securit", "cri_classe"):       ("ingest_securit_serie",  "yearly_doc",   "cri_classe", "cvm_securit_serie"),
    ("securit", "ots_classe"):       ("ingest_securit_serie",  "yearly_doc",   "ots_classe", "cvm_securit_serie"),
    ("securit", "cra_fluxo"):        ("ingest_securit_fluxo",  "yearly_doc",   "cra_fluxo",  "cvm_securit_fluxo"),
    ("securit", "cri_fluxo"):        ("ingest_securit_fluxo",  "yearly_doc",   "cri_fluxo",  "cvm_securit_fluxo"),
    ("securit", "ots_fluxo"):        ("ingest_securit_fluxo",  "yearly_doc",   "ots_fluxo",  "cvm_securit_fluxo"),
    ("securit", "dfin_cra"):         ("ingest_securit_dfin",   "yearly_instr", "dfin_cra",   "cvm_securit_dfin"),
    ("securit", "dfin_cri"):         ("ingest_securit_dfin",   "yearly_instr", "dfin_cri",   "cvm_securit_dfin"),
}


@dataclass(frozen=True)
class Resolved:
    method_name: str
    convention: str            # "monthly" | "yearly_doc" | "yearly_instr"
    table: str                 # target Supabase table for this slice
    needs_month: bool          # True when convention == "monthly"
    extra_arg: Optional[str]   # doc_type / instrument_type passed to the method


def resolve(entity: str, doc_type: str) -> Resolved:
    """Look up (entity, doc_type). Raises KeyError with a helpful message if unknown."""
    key = (entity.lower().strip(), doc_type.lower().strip())
    if key not in _TABLE:
        raise KeyError(
            f"Unknown (entity, doc_type)=({entity!r}, {doc_type!r}). "
            f"Run GET /api/dispatch to list valid pairs."
        )
    method, conv, extra, table = _TABLE[key]
    return Resolved(method, conv, table, conv == "monthly", extra)


def build_call(
    ingestor, resolved: Resolved, year: int, month: Optional[int]
) -> Callable[[], Awaitable[int]]:
    """Return a thunk that, when awaited, executes the right ingest method."""
    method = getattr(ingestor, resolved.method_name)

    if resolved.convention == "monthly":
        if month is None:
            raise ValueError(f"{resolved.method_name} requires `month` (1-12)")
        return lambda: method(year, month)

    # yearly_doc and yearly_instr both take (extra_arg, year)
    return lambda: method(resolved.extra_arg, year)


def all_pairs() -> Dict[str, list]:
    """Return the dispatch matrix grouped by entity — used by GET /api/dispatch."""
    grouped: Dict[str, list] = {}
    for (entity, doc_type), (method, conv, _, table) in _TABLE.items():
        grouped.setdefault(entity, []).append({
            "doc_type": doc_type,
            "method": method,
            "convention": conv,
            "table": table,
        })
    for v in grouped.values():
        v.sort(key=lambda r: r["doc_type"])
    return grouped
